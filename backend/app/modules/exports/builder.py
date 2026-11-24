"""J02 body: build one export file (design B07 §3.5, D1, D5, D7, D13, D16, D17).

    queued -> running -> (count, stream, write, upload) -> done | failed

Called by the arq job `build_export` with plain values only. Every outcome is
recorded on the job row, in one notification to the requester and in one
audit line. Never raises for an expected failure; the temp file is always
removed. Idempotent: only a `queued` job is picked up, so a duplicate
delivery of the same job does nothing.
"""

import csv
import os
import tempfile
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audit, db, storage
from app.core.errors import AppError
from app.core.permissions import load_access
from app.core.tenancy import TenantContext, tenant_session
from app.models.public import Organization, OrgMembership, User
from app.modules.exports.models import ExportJob
from app.modules.exports.service import AUDIT_ENTITY, CONTENT_TYPES
from app.modules.exports.sources import ExportContext, get_source, parse_export_filters
from app.modules.notifications.service import notify

log = structlog.get_logger("app.exports.builder")

BATCH_SIZE = 500  # rows fetched per round trip from the server-side cursor
MAX_ERROR_LEN = 500
EXPORT_RUN = "export:run"
# D16: a cell starting with one of these is a formula in Excel/LibreOffice
# (CSV injection, OWASP). Such cells get a leading apostrophe.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ExportFailed(Exception):
    """An expected failure; the message is shown to the user as-is."""


def object_key(slug: str, job: ExportJob) -> str:
    return f"exports/{slug}/{job.created_at:%Y/%m}/{job.id}.{job.format}"


# --------------------------------------------------------------------------- #
# cell values
# --------------------------------------------------------------------------- #
def _safe_text(s: str) -> str:
    return "'" + s if s.startswith(FORMULA_PREFIXES) else s


def csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, int | float):
        return str(v)  # numbers stay numbers (a negative number is not a formula)
    return _safe_text(str(v))


def xlsx_cell(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float):
        return v
    if isinstance(v, datetime):
        # openpyxl cannot store tz-aware datetimes: write UTC, naive.
        return v.astimezone(UTC).replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, date):
        return v
    # Control characters are not allowed in XLSX XML: drop them.
    return _safe_text(ILLEGAL_CHARACTERS_RE.sub("", str(v)))


# --------------------------------------------------------------------------- #
# writers: header first, then add(batch) repeatedly, then close()
# --------------------------------------------------------------------------- #
class _CsvWriter:
    def __init__(self, path: Path, header: list[str]) -> None:
        # D16: UTF-8 with BOM so Excel on Windows does not read it as ANSI.
        self._fh = path.open("w", encoding="utf-8-sig", newline="")
        self._w = csv.writer(self._fh, lineterminator="\r\n")
        self._w.writerow(header)

    def add(self, rows: list[list[Any]]) -> None:
        self._w.writerows([[csv_cell(v) for v in r] for r in rows])

    def close(self) -> None:
        self._fh.close()


class _XlsxWriter:
    def __init__(self, path: Path, header: list[str]) -> None:
        self._path = path
        self._wb = Workbook(write_only=True)  # streams rows; memory stays flat
        self._ws = self._wb.create_sheet("export")
        self._ws.append(header)

    def add(self, rows: list[list[Any]]) -> None:
        for r in rows:
            self._ws.append([xlsx_cell(v) for v in r])

    def close(self) -> None:
        self._wb.save(self._path)


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #
async def _org(slug: str) -> Organization | None:
    async with db.get_session_factory()() as s:
        return await s.scalar(select(Organization).where(Organization.slug == slug))


async def _claim(schema: str, export_id: uuid.UUID) -> tuple[str, ExportJob | None]:
    """queued -> running under a row lock. Returns (status seen, job if claimed)."""
    async with tenant_session(schema) as ts:
        job = await ts.get(ExportJob, export_id, with_for_update=True)
        if job is None:
            return "missing", None
        if job.status != "queued":
            return job.status, None
        job.status = "running"
        await ts.commit()
        return "running", job


async def _check_access(org: Organization, job: ExportJob, read_key: str) -> None:
    """D3 again at run time: roles may have changed since POST /exports."""
    async with db.get_session_factory()() as s:
        user = await s.get(User, job.requested_by)
        member = await s.scalar(
            select(OrgMembership.status).where(
                OrgMembership.user_id == job.requested_by, OrgMembership.org_id == org.id
            )
        )
    if user is None or not user.is_active or (member != "active" and not user.is_platform_admin):
        raise ExportFailed("the requester is no longer an active member")
    ctx = TenantContext(org_id=org.id, slug=org.slug, name=org.name, schema_name=org.schema_name)
    rs = await load_access(None, user, ctx)  # no cache: always the current grants
    missing = [k for k in (EXPORT_RUN, read_key) if k not in rs.permissions]
    if missing:
        raise ExportFailed(f"the requester no longer has {', '.join(missing)}")


async def _write(
    ts: AsyncSession, settings: Settings, org: Organization, job: ExportJob, path: Path
) -> int:
    src = get_source(job.resource)
    try:
        parsed = parse_export_filters(src, job.filters or {})
    except AppError as exc:  # stored filters no longer valid (module changed)
        raise ExportFailed(f"invalid filters: {exc.message}") from exc
    ctx = ExportContext(user_id=job.requested_by, org_id=org.id, slug=org.slug)
    stmt = src.statement(ctx, parsed)

    total = int(
        await ts.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )
    if total > settings.export_max_rows:
        # D7: never a silently truncated file.
        raise ExportFailed(
            f"{total} rows match, the limit is {settings.export_max_rows}; narrow the filters"
        )

    writer = (_CsvWriter if job.format == "csv" else _XlsxWriter)(path, src.columns)
    written = 0
    try:
        result = await ts.stream(stmt.execution_options(yield_per=BATCH_SIZE))
        async for part in result.partitions(BATCH_SIZE):
            rows = await src.rows(ts, list(part))
            writer.add(rows)
            written += len(rows)
    finally:
        writer.close()
    return written


async def _finish(
    schema: str,
    slug: str,
    export_id: uuid.UUID,
    *,
    ok: bool,
    key: str | None = None,
    rows: int | None = None,
    error: str | None = None,
    retention_days: int = 0,
) -> None:
    """Record the outcome, notify the requester (D1) and audit (D13), in one commit."""
    async with tenant_session(schema) as ts:
        job = await ts.get(ExportJob, export_id, with_for_update=True)
        if job is None:  # deleted meanwhile (by hand): nothing to record
            return
        job.status = "done" if ok else "failed"
        job.object_key, job.row_count = key, rows
        job.error = None if ok else (error or "export failed")[:MAX_ERROR_LEN]
        job.finished_at = datetime.now(UTC)
        data = {"export_id": str(job.id), "resource": job.resource, "format": job.format}
        if ok:
            keep = f" within {retention_days} days" if retention_days else ""
            notify(
                ts,
                job.requested_by,
                "export.done",
                f"Your {job.resource} export is ready",
                body=f"{rows} rows, {job.format.upper()}. Download it from Exports{keep}.",
                data=data,
            )
        else:
            notify(
                ts,
                job.requested_by,
                "export.failed",
                f"Your {job.resource} export failed",
                body=job.error,
                data=data,
            )
        requester = job.requested_by
    audit.record(
        "exports.finish",
        entity=AUDIT_ENTITY,
        entity_id=str(export_id),
        org=slug,
        actor="worker",
        diff={
            "requested_by": str(requester),
            "status": "done" if ok else "failed",
            "row_count": rows,
            "error": None if ok else error,
        },
        result="ok" if ok else "error",
    )


async def run_export(settings: Settings, org_slug: str, export_id: uuid.UUID) -> str:
    """Build one export. Returns the job's final status ("missing" if no such job)."""
    bound = log.bind(org=org_slug, export_id=str(export_id))
    org = await _org(org_slug)
    if org is None:
        bound.warning("exports.job_org_missing")
        return "missing"
    status, job = await _claim(org.schema_name, export_id)
    if job is None:
        bound.info("exports.job_skipped", status=status)
        return status

    bound.info("exports.job_started", resource=job.resource, format=job.format)
    fd, tmp = tempfile.mkstemp(prefix="export-", suffix=f".{job.format}")
    path = Path(tmp)
    try:
        os.close(fd)
        key = object_key(org.slug, job)
        try:
            await _check_access(org, job, get_source(job.resource).permission)
            async with tenant_session(org.schema_name) as ts:
                rows = await _write(ts, settings, org, job, path)
            await storage.put_file(settings, key, path, CONTENT_TYPES[job.format])
        except ExportFailed as exc:
            bound.info("exports.job_failed", reason=str(exc))
            await _finish(org.schema_name, org.slug, export_id, ok=False, error=str(exc))
            return "failed"
        except storage.StorageError as exc:
            bound.error("exports.job_storage_failed", error=exc.message)
            await _finish(
                org.schema_name,
                org.slug,
                export_id,
                ok=False,
                error="file storage is unavailable; try again later",
            )
            return "failed"
        except Exception as exc:  # a bug: keep details in the log, not in the UI
            bound.exception("exports.job_crashed", error=f"{type(exc).__name__}: {exc}")
            await _finish(
                org.schema_name,
                org.slug,
                export_id,
                ok=False,
                error="internal error while building the export",
            )
            return "failed"
        await _finish(
            org.schema_name,
            org.slug,
            export_id,
            ok=True,
            key=key,
            rows=rows,
            retention_days=settings.export_retention_days,
        )
        bound.info("exports.job_done", rows=rows, key=key, bytes=path.stat().st_size)  # noqa: ASYNC240
        return "done"
    finally:
        path.unlink(missing_ok=True)  # noqa: ASYNC240 (local temp file)
