"""B05: core.storage against a real RustFS (testcontainer), design §3.1, D1–D9, D16."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from testcontainers.core.container import DockerContainer

from app.config import DEFAULT_ALLOWED_MIME_TYPES, Settings
from app.core import storage
from tests.conftest import S3_BUCKET, S3_KEY, S3_SECRET, rustfs_endpoint


# --------------------------------------------------------------------------- #
# unit
# --------------------------------------------------------------------------- #
def test_object_key_format() -> None:
    fid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    key = storage.object_key("acme", fid, datetime(2026, 3, 7, tzinfo=UTC))
    assert key == "acme/2026/03/11111111-2222-3333-4444-555555555555"


def test_lifetimes() -> None:
    assert storage.PUT_EXPIRES_S == 900
    assert storage.GET_EXPIRES_S == 60


def test_content_disposition_non_ascii() -> None:
    cd = storage.content_disposition('Résumé "2026".pdf')
    assert cd.startswith("attachment; ")
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%20%222026%22.pdf" in cd
    # plain-ASCII fallback for old clients: no quotes or non-ASCII inside
    assert 'filename="Resume 2026.pdf"' in cd


def test_allowed_mime_types_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_MIME_TYPES", " Application/PDF, image/png ,")
    assert Settings(audit_log_dir=str(tmp_path)).allowed_mime_types == [
        "application/pdf",
        "image/png",
    ]
    monkeypatch.setenv("ALLOWED_MIME_TYPES", "")  # compose passes "" when unset
    assert Settings(audit_log_dir=str(tmp_path)).allowed_mime_types == list(
        DEFAULT_ALLOWED_MIME_TYPES
    )
    monkeypatch.delenv("ALLOWED_MIME_TYPES")
    assert "application/pdf" in Settings(audit_log_dir=str(tmp_path)).allowed_mime_types


# --------------------------------------------------------------------------- #
# integration
# --------------------------------------------------------------------------- #
@pytest.fixture
def s3_settings(audit_dir: Path, rustfs_container: DockerContainer) -> Settings:
    ep = rustfs_endpoint(rustfs_container)
    return Settings(
        app_env="test",
        audit_log_dir=str(audit_dir),
        s3_endpoint=ep,
        s3_public_endpoint=ep,
        s3_access_key=S3_KEY,
        s3_secret_key=S3_SECRET,
        s3_bucket=S3_BUCKET,
    )


def _key() -> str:
    return f"t/{uuid.uuid4()}"


@pytest.mark.integration
def test_put_head_get_delete_round_trip(s3_settings: Settings) -> None:
    key = _key()
    url, headers = asyncio.run(storage.presign_put(s3_settings, key, "application/pdf"))
    assert headers == {"Content-Type": "application/pdf"}
    assert "X-Amz-Expires=900" in url
    r = httpx.put(url, content=b"%PDF-1.4 hello", headers=headers)
    assert r.status_code == 200, r.text

    info = asyncio.run(storage.head(s3_settings, key))
    assert info == storage.ObjectInfo(size=14, content_type="application/pdf")

    get_url = asyncio.run(storage.presign_get(s3_settings, key, "Résumé.pdf"))
    assert "X-Amz-Expires=60" in get_url
    g = httpx.get(get_url)
    assert g.status_code == 200
    assert g.content == b"%PDF-1.4 hello"
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9.pdf" in g.headers["content-disposition"]

    asyncio.run(storage.delete(s3_settings, key))
    assert asyncio.run(storage.head(s3_settings, key)) is None


@pytest.mark.integration
def test_put_with_other_content_type_is_refused(s3_settings: Settings) -> None:
    """Review focus 3: Content-Type is part of the signature (D6)."""
    key = _key()
    url, _ = asyncio.run(storage.presign_put(s3_settings, key, "application/pdf"))
    r = httpx.put(url, content=b"MZ", headers={"Content-Type": "application/x-msdownload"})
    assert r.status_code == 403
    assert asyncio.run(storage.head(s3_settings, key)) is None


@pytest.mark.integration
def test_put_file_uploads_from_disk(s3_settings: Settings, tmp_path: Path) -> None:
    """B07 §3.8: the worker uploads an export file through the internal client."""
    key = _key()
    src = tmp_path / "e.csv"
    src.write_bytes("\ufeffid,title\r\n1,Café\r\n".encode())
    asyncio.run(storage.put_file(s3_settings, key, src, "text/csv"))
    info = asyncio.run(storage.head(s3_settings, key))
    assert info == storage.ObjectInfo(size=src.stat().st_size, content_type="text/csv")
    g = httpx.get(asyncio.run(storage.presign_get(s3_settings, key, "items.csv")))
    assert g.content == src.read_bytes()
    asyncio.run(storage.delete(s3_settings, key))


@pytest.mark.integration
def test_missing_objects(s3_settings: Settings) -> None:
    key = _key()
    assert asyncio.run(storage.head(s3_settings, key)) is None
    asyncio.run(storage.delete(s3_settings, key))  # no error (D12: missing = done)


@pytest.mark.integration
def test_check_bucket(s3_settings: Settings) -> None:
    asyncio.run(storage.check_bucket(s3_settings))
    bad = s3_settings.model_copy(update={"s3_bucket": "no-such-bucket-b05"})
    with pytest.raises(storage.StorageError):
        asyncio.run(storage.check_bucket(bad))


def test_unreachable_endpoint_raises_storage_error(unit_settings: Settings) -> None:
    """D16: RustFS down -> StorageError (503), presigning still works (offline)."""
    s = unit_settings.model_copy(
        update={"s3_endpoint": "http://127.0.0.1:1", "s3_public_endpoint": "http://127.0.0.1:1"}
    )
    url, _ = asyncio.run(storage.presign_put(s, "k", "text/plain"))
    assert url.startswith("http://127.0.0.1:1/")
    with pytest.raises(storage.StorageError) as exc:
        asyncio.run(storage.head(s, "k"))
    assert exc.value.status == 503
    assert exc.value.code == "storage_unavailable"
    assert "X-Amz" not in exc.value.message
