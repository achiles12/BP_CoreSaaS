"""Object storage (S07): the ONE place that talks to RustFS (design B05 §3.1).

RustFS is S3-compatible and path-style only (B00 D11). Two kinds of client:

- the **public** client is configured with `S3_PUBLIC_ENDPOINT` and is used only
  to *presign* URLs. Presigning is pure computation (no network call), and the
  host is part of the signature, so URLs must be signed for the address the
  browser will use (D2/D3), e.g. http://<server LAN IP>:9000 on the LAN.
- the **internal** client uses `S3_ENDPOINT` (http://rustfs:9000 inside compose)
  for HEAD, DELETE and the readiness check.

Every network failure is turned into `StorageError` (503 storage_unavailable,
D16). Messages and logs name the operation and key, never a presigned URL
(it is a bearer credential until it expires).
"""

import unicodedata
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aioboto3
import structlog
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings
from app.core.errors import AppError

log = structlog.get_logger("app.core.storage")

PUT_EXPIRES_S = 900  # presigned upload lifetime (backend_processes.md §6: 15 min)
GET_EXPIRES_S = 60  # presigned download lifetime (system_design.md §8)

# Short timeouts: an API request must not hang on a dead RustFS. One retry is
# enough to ride over a dropped keep-alive connection.
_BOTO_CONFIG = BotoConfig(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    connect_timeout=3,
    read_timeout=10,
    retries={"max_attempts": 2, "mode": "standard"},
)
_session = aioboto3.Session()

# S3 error codes that mean "the object/bucket is not there" on HEAD/GET.
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class StorageError(AppError):
    """RustFS unreachable or misbehaving (D16)."""

    status, code, default_message = 503, "storage_unavailable", "File storage is unavailable"


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None


def object_key(org_slug: str, file_id: uuid.UUID, now: datetime) -> str:
    """`{org_slug}/{yyyy}/{mm}/{file_uuid}` (D8). The file name never appears in a key."""
    return f"{org_slug}/{now:%Y}/{now:%m}/{file_id}"


def content_disposition(filename: str) -> str:
    """`attachment` header with an ASCII fallback plus the RFC 5987 UTF-8 name (D9).

    The fallback strips accents (NFKD), drops anything non-ASCII and removes
    characters that would break the quoted string (`"` and `\\`).
    """
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    ascii_name = "".join(c for c in ascii_name if c not in '"\\' and c.isprintable()).strip()
    ascii_name = ascii_name or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@asynccontextmanager
async def _client(settings: Settings, *, public: bool = False) -> AsyncIterator[Any]:
    endpoint = settings.s3_public_endpoint if public else settings.s3_endpoint
    # aioboto3 ships no precise type stubs for its client context manager.
    async with _session.client(  # pyright: ignore[reportGeneralTypeIssues]
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=_BOTO_CONFIG,
    ) as s3:
        yield s3


def _fail(op: str, key: str | None, exc: Exception) -> StorageError:
    """Log the cause (no URLs) and build the 503."""
    log.error("storage.error", op=op, key=key, error=f"{type(exc).__name__}: {exc}"[:500])
    return StorageError(f"File storage is unavailable ({op})")


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES


async def presign_put(
    settings: Settings, key: str, content_type: str
) -> tuple[str, dict[str, str]]:
    """Presigned PUT valid PUT_EXPIRES_S. Returns (url, headers the client MUST send).

    Content-Type is signed (D6): a PUT with any other type fails with 403.
    """
    try:
        async with _client(settings, public=True) as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=PUT_EXPIRES_S,
            )
    except (BotoCoreError, ClientError) as exc:
        raise _fail("presign_put", key, exc) from exc
    return url, {"Content-Type": content_type}


async def presign_get(settings: Settings, key: str, filename: str) -> str:
    """Presigned GET valid GET_EXPIRES_S that downloads as `filename` (D9)."""
    try:
        async with _client(settings, public=True) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": settings.s3_bucket,
                    "Key": key,
                    "ResponseContentDisposition": content_disposition(filename),
                },
                ExpiresIn=GET_EXPIRES_S,
            )
    except (BotoCoreError, ClientError) as exc:
        raise _fail("presign_get", key, exc) from exc
    return url


async def head(settings: Settings, key: str) -> ObjectInfo | None:
    """Size and type of a stored object, or None when it does not exist."""
    try:
        async with _client(settings) as s3:
            r = await s3.head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise _fail("head", key, exc) from exc
    except BotoCoreError as exc:
        raise _fail("head", key, exc) from exc
    return ObjectInfo(size=int(r["ContentLength"]), content_type=r.get("ContentType"))


async def put_file(settings: Settings, key: str, path: Path, content_type: str) -> None:
    """Upload a local file through the INTERNAL endpoint (B07 §3.8: export files).

    Used by the worker only; browsers upload via presigned PUT instead. The
    file is streamed from disk, so a large export never sits in memory.
    """
    try:
        async with _client(settings) as s3:
            with path.open("rb") as fh:
                await s3.put_object(
                    Bucket=settings.s3_bucket, Key=key, Body=fh, ContentType=content_type
                )
    except (BotoCoreError, ClientError) as exc:
        raise _fail("put_file", key, exc) from exc
    log.info("storage.put", key=key, size=path.stat().st_size)  # noqa: ASYNC240 (local stat)


async def delete(settings: Settings, key: str) -> None:
    """Remove an object. A missing object is not an error (S3 DELETE is idempotent)."""
    try:
        async with _client(settings) as s3:
            await s3.delete_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return
        raise _fail("delete", key, exc) from exc
    except BotoCoreError as exc:
        raise _fail("delete", key, exc) from exc
    log.info("storage.deleted", key=key)


async def check_bucket(settings: Settings) -> None:
    """Signed HeadBucket: proves endpoint, credentials and bucket (/health/ready)."""
    try:
        async with _client(settings) as s3:
            await s3.head_bucket(Bucket=settings.s3_bucket)
    except (BotoCoreError, ClientError) as exc:
        raise _fail("head_bucket", None, exc) from exc
