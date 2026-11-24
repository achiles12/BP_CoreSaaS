"""Files rules (design B05 §3.4, D5–D16; backend_processes.md §6).

Lifecycle: presign-upload inserts a `pending` row and returns a presigned PUT
-> the browser PUTs straight to RustFS -> confirm HEADs the object and marks
the row `active` -> delete marks it `deleted` -> J04 removes the object and the
row (worker/jobs.py).

Every query runs in the caller's tenant session, so a file id from another
tenant is simply not found (404, D15). Presigned URLs are never logged.
"""

import unicodedata
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audit, storage
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.pagination import FilterField, ListQuery, ListSpec, paginate
from app.core.permissions import TenantAccess
from app.models.public import User
from app.models.tenant import File
from app.modules.files.schemas import DownloadOut, FileOut, PresignIn, PresignOut

log = structlog.get_logger("app.files")

MAX_FILE_NAME_LEN = 255


# --------------------------------------------------------------------------- #
# errors (D5, D7)
# --------------------------------------------------------------------------- #
class FileTooLarge(AppError):
    status, code, default_message = 413, "file_too_large", "File is too large"


class UnsupportedFileType(AppError):
    status, code, default_message = 415, "unsupported_file_type", "File type is not allowed"


class UploadIncomplete(Conflict):
    code, default_message = "upload_incomplete", "The file has not been uploaded yet"


class UploadMismatch(ValidationFailed):
    code, default_message = "upload_mismatch", "Uploaded file does not match what was declared"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def clean_name(raw: str) -> str:
    """Keep only the base name, without control characters (D5, review focus 2).

    Browsers send just the base name, but other clients may send a full path
    ("C:\\x\\a.pdf", "../../etc/passwd"). Both separators are treated as path
    separators. The name is NFC-normalised so "é" is stored one way only.
    """
    name = unicodedata.normalize("NFC", raw)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # Category "C*" = control, format, surrogate, private use, unassigned.
    name = "".join(ch for ch in name if not unicodedata.category(ch).startswith("C")).strip()
    if not name or name in {".", ".."}:
        raise ValidationFailed(
            "File name is empty", fields=[{"field": "name", "message": "must not be empty"}]
        )
    if len(name) > MAX_FILE_NAME_LEN:
        raise ValidationFailed(
            f"File name is longer than {MAX_FILE_NAME_LEN} characters",
            fields=[{"field": "name", "message": f"at most {MAX_FILE_NAME_LEN} characters"}],
        )
    return name


def _now() -> datetime:
    return datetime.now(UTC)


def _file_out(f: File, uploader_name: str | None) -> FileOut:
    return FileOut(
        id=f.id,
        name=f.name,
        mime_type=f.mime_type,
        size_bytes=f.size_bytes,
        status=f.status,
        uploaded_by=f.uploaded_by,
        uploader_name=uploader_name,
        created_at=f.created_at,
    )


def _with_uploader() -> Select:
    # Outer join: a missing user row must never hide a file (FK makes it rare).
    return select(File, User.full_name).outerjoin(User, User.id == File.uploaded_by)


async def _active_or_404(ts: AsyncSession, file_id: uuid.UUID, *, lock: bool = False) -> File:
    stmt = select(File).where(File.id == file_id, File.status == "active")
    if lock:
        stmt = stmt.with_for_update()
    f = await ts.scalar(stmt)
    if f is None:
        raise NotFound("File not found")
    return f


async def _uploader_name(ts: AsyncSession, user_id: uuid.UUID) -> str | None:
    return await ts.scalar(select(User.full_name).where(User.id == user_id))


# --------------------------------------------------------------------------- #
# upload
# --------------------------------------------------------------------------- #
async def presign_upload(
    ts: AsyncSession, settings: Settings, access: TenantAccess, body: PresignIn
) -> PresignOut:
    """Validate (D5), insert a pending row, return a presigned PUT (D6).

    Validation happens before anything is written, so a rejected upload leaves
    no row and no object (C6 step 5).
    """
    bound = log.bind(org=access.tenant.slug, actor=str(access.user_id))
    name = clean_name(body.name)
    limit = settings.max_upload_mb * 1024 * 1024
    if body.size_bytes > limit:
        bound.info("files.presign_rejected", reason="too_large", size_bytes=body.size_bytes)
        raise FileTooLarge(f"File is larger than {settings.max_upload_mb} MB")
    if body.mime_type not in settings.allowed_mime_types:
        bound.info("files.presign_rejected", reason="mime", mime_type=body.mime_type)
        raise UnsupportedFileType(f"File type {body.mime_type} is not allowed")

    file_id = uuid.uuid4()
    key = storage.object_key(access.tenant.slug, file_id, _now())
    ts.add(
        File(
            id=file_id,
            name=name,
            mime_type=body.mime_type,
            size_bytes=body.size_bytes,
            object_key=key,
            status="pending",
            uploaded_by=access.user_id,
        )
    )
    # Commit BEFORE presigning: if presigning fails, the pending row is an
    # orphan that J04 removes after 24 h; nothing points at a missing row.
    await ts.commit()
    url, headers = await storage.presign_put(settings, key, body.mime_type)
    bound.info("files.presigned", file_id=str(file_id), size_bytes=body.size_bytes)
    return PresignOut(
        file_id=file_id, upload_url=url, headers=headers, expires_in=storage.PUT_EXPIRES_S
    )


async def confirm_upload(
    ts: AsyncSession, settings: Settings, access: TenantAccess, file_id: uuid.UUID
) -> FileOut:
    """HEAD the object and activate the row (D7).

    - only the uploader may confirm their own pending file (others: 404)
    - an already-active file of the uploader: 200, no change (idempotent)
    - object missing: 409, row stays pending (the client may PUT and retry)
    - size/type differs from what was declared: delete object, row deleted, 422
    """
    bound = log.bind(org=access.tenant.slug, actor=str(access.user_id), file_id=str(file_id))
    f = await ts.scalar(
        select(File)
        .where(File.id == file_id, File.uploaded_by == access.user_id)
        .with_for_update()  # two concurrent confirms: the second waits, then sees "active"
    )
    if f is None or f.status == "deleted":
        raise NotFound("File not found")
    if f.status == "active":
        bound.info("files.confirm_repeat")
        return _file_out(f, await _uploader_name(ts, f.uploaded_by))

    info = await storage.head(settings, f.object_key)
    if info is None:
        bound.info("files.confirm_missing_object")
        raise UploadIncomplete()

    got_type = (info.content_type or "").split(";")[0].strip().lower()
    if info.size != f.size_bytes or got_type != f.mime_type:
        await storage.delete(settings, f.object_key)
        f.status, f.deleted_at = "deleted", _now()
        await ts.commit()
        diff = {"declared": [f.size_bytes, f.mime_type], "stored": [info.size, got_type]}
        bound.warning("files.confirm_mismatch", **diff)
        audit.record(
            "files.upload",
            entity="file",
            entity_id=str(f.id),
            org=access.tenant.slug,
            actor=str(access.user_id),
            diff=diff,
            result="rejected",
        )
        raise UploadMismatch()

    f.status = "active"
    await ts.commit()
    await ts.refresh(f)
    bound.info("files.uploaded", size_bytes=f.size_bytes)
    audit.record(
        "files.upload",
        entity="file",
        entity_id=str(f.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"status": ["pending", "active"], "name": f.name, "size_bytes": f.size_bytes},
    )
    return _file_out(f, await _uploader_name(ts, f.uploaded_by))


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #
def _escape_like(q: str) -> str:
    """Literal substring search: user input must not act as LIKE wildcards."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# B06 D9: what GET /files may sort and filter by.
FILES_LIST = ListSpec(
    sort={"name": File.name, "size_bytes": File.size_bytes, "created_at": File.created_at},
    default_sort="-created_at",
    filters={
        "mime_type": FilterField(File.mime_type, "text"),
        "uploaded_by": FilterField(File.uploaded_by, "uuid"),
        "created_at": FilterField(File.created_at, "datetime", ranges=True),
    },
)


def files_statement(user_id: uuid.UUID, q: str | None, mine: bool, lq: ListQuery) -> Select:
    """The ONE query behind GET /files and the files export (B07 D4).

    Active files (D10), sorted/filtered by `lq` (B06). `q`: name contains;
    `mine`: only files `user_id` uploaded.
    """
    stmt = lq.apply(_with_uploader().where(File.status == "active"))
    if q and q.strip():
        stmt = stmt.where(File.name.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))
    if mine:
        stmt = stmt.where(File.uploaded_by == user_id)
    return stmt


async def list_files(
    ts: AsyncSession, access: TenantAccess, q: str | None, mine: bool, lq: ListQuery
) -> tuple[list[FileOut], int]:
    rows, total = await paginate(ts, files_statement(access.user_id, q, mine, lq), lq.page)
    return [_file_out(f, n) for f, n in rows], total


async def get_file(ts: AsyncSession, file_id: uuid.UUID) -> FileOut:
    row = (
        await ts.execute(_with_uploader().where(File.id == file_id, File.status == "active"))
    ).first()
    if row is None:
        raise NotFound("File not found")
    return _file_out(row[0], row[1])


async def download_url(
    ts: AsyncSession, settings: Settings, access: TenantAccess, file_id: uuid.UUID
) -> DownloadOut:
    """Presigned GET, 60 s, saved under the original name (D9)."""
    f = await _active_or_404(ts, file_id)
    url = await storage.presign_get(settings, f.object_key, f.name)
    log.info(
        "files.download_url", org=access.tenant.slug, actor=str(access.user_id), file_id=str(f.id)
    )
    return DownloadOut(url=url, expires_in=storage.GET_EXPIRES_S)


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #
async def delete_file(ts: AsyncSession, access: TenantAccess, file_id: uuid.UUID) -> None:
    """Soft delete (D11). The object stays until J04 runs."""
    f = await _active_or_404(ts, file_id, lock=True)
    f.status, f.deleted_at = "deleted", _now()
    await ts.commit()
    log.info("files.deleted", org=access.tenant.slug, actor=str(access.user_id), file_id=str(f.id))
    audit.record(
        "files.delete",
        entity="file",
        entity_id=str(f.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"status": ["active", "deleted"]},
    )
