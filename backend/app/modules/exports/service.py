"""Export requests (design B07 §3.4, D3–D9, D13, D18; app_flows.md F9).

POST validates everything a job could reject up front (resource, read key,
filters) so a bad request is a 422/403, never a failed job. The job itself is
modules/exports/builder.py. Users see only their own exports (D8).
"""

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audit, storage
from app.core.errors import NotFound, PermissionDenied, ServiceUnavailable
from app.core.pagination import PageParams, paginate
from app.core.permissions import TenantAccess
from app.modules.exports.models import ExportJob
from app.modules.exports.schemas import ExportCreate, ExportOut
from app.modules.exports.sources import get_source, parse_export_filters

log = structlog.get_logger("app.exports")

BUILD_EXPORT_JOB = "build_export"  # arq function name, worker/jobs.py
AUDIT_ENTITY = "export"
CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def download_name(job: ExportJob) -> str:
    """e.g. items-export-20261120-1552.csv (time of completion, UTC)."""
    when = job.finished_at or job.created_at
    return f"{job.resource}-export-{when:%Y%m%d-%H%M}.{job.format}"


def expires_at(job: ExportJob, settings: Settings) -> datetime | None:
    if job.status != "done" or job.finished_at is None or settings.export_retention_days == 0:
        return None
    return job.finished_at + timedelta(days=settings.export_retention_days)


def to_out(job: ExportJob, settings: Settings, url: str | None = None) -> ExportOut:
    return ExportOut(
        id=job.id,
        resource=job.resource,
        format=job.format,
        filters=job.filters or {},
        status=job.status,
        row_count=job.row_count,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
        expires_at=expires_at(job, settings),
        download_url=url,
        download_expires_in=storage.GET_EXPIRES_S if url else None,
    )


async def create_export(
    ts: AsyncSession, redis: object, settings: Settings, access: TenantAccess, body: ExportCreate
) -> ExportOut:
    src = get_source(body.resource)  # 422 when unknown
    if src.permission not in access.permissions:
        log.info("exports.denied", key=src.permission, resource=src.resource)
        raise PermissionDenied(f"Missing permission {src.permission}")
    parse_export_filters(src, body.filters)  # 422 now rather than a failed job later

    job = ExportJob(
        requested_by=access.user_id,
        resource=src.resource,
        format=body.format,
        filters=body.filters,
    )
    ts.add(job)
    await ts.commit()
    await ts.refresh(job)
    audit.record(
        "exports.create",
        entity=AUDIT_ENTITY,
        entity_id=str(job.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"resource": job.resource, "format": job.format, "filters": job.filters},
    )

    try:
        await redis.enqueue_job(BUILD_EXPORT_JOB, str(job.id), access.tenant.slug)  # type: ignore[attr-defined]
    except Exception as exc:
        # D18: without a queued job the row would sit in "queued" forever.
        log.error("exports.queue_failed", export_id=str(job.id), error=str(exc))
        job.status, job.error = "failed", "could not queue the export job; try again"
        await ts.commit()
        raise ServiceUnavailable("Export queue is unavailable, try again later") from exc
    log.info(
        "exports.queued",
        org=access.tenant.slug,
        export_id=str(job.id),
        resource=job.resource,
        format=job.format,
    )
    return to_out(job, settings)


async def _own_or_404(ts: AsyncSession, access: TenantAccess, export_id: uuid.UUID) -> ExportJob:
    job = await ts.scalar(
        select(ExportJob).where(ExportJob.id == export_id, ExportJob.requested_by == access.user_id)
    )
    if job is None:
        raise NotFound("Export not found")
    return job


async def get_export(
    ts: AsyncSession, settings: Settings, access: TenantAccess, export_id: uuid.UUID
) -> ExportOut:
    """Status; a fresh 60 s download link while done and the file exists (D9)."""
    job = await _own_or_404(ts, access, export_id)
    url = None
    if job.status == "done" and job.object_key:
        # HEAD first: never hand out a link to an object that is gone
        # (removed by hand, bucket reset). Costs one call per poll while done.
        if await storage.head(settings, job.object_key) is not None:
            url = await storage.presign_get(settings, job.object_key, download_name(job))
        else:
            log.warning("exports.object_missing", export_id=str(job.id), key=job.object_key)
    return to_out(job, settings, url)


async def list_exports(
    ts: AsyncSession, settings: Settings, access: TenantAccess, page: PageParams
) -> tuple[list[ExportOut], int]:
    """The caller's exports, newest first. No links here: GET /exports/{id} mints them."""
    stmt = (
        select(ExportJob)
        .where(ExportJob.requested_by == access.user_id)
        .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
    )
    rows, total = await paginate(ts, stmt, page)
    return [to_out(r[0], settings) for r in rows], total
