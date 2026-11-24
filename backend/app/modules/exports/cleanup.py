"""Export retention cleanup (design B07 D2, D17).

Shared by the arq cron `cleanup_exports` (EXPORT_CLEANUP_HOUR:MINUTE UTC) and
the CLI `cleanup-exports`. For every active or suspended tenant:

1. done jobs finished more than EXPORT_RETENTION_DAYS ago (skipped when 0):
   delete the object (missing = done), set status `expired`, clear object_key
2. queued/running jobs older than STUCK_AFTER: the worker died or never got
   them; set `failed` and notify the requester

Per-tenant try/except as J04; RustFS down stops that tenant, the next run
retries. Idempotent: a second run changes nothing.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from app.config import Settings
from app.core import audit, storage
from app.core.tenancy import tenant_session
from app.modules.exports.models import ExportJob
from app.modules.files.cleanup import _tenants as cleanup_tenants  # same tenant selection as J04
from app.modules.notifications.service import notify

log = structlog.get_logger("app.exports.cleanup")

STUCK_AFTER = timedelta(hours=1)  # job_timeout is 300 s; 1 h is far past any real run
BATCH_SIZE = 500
STUCK_ERROR = "the export did not finish (the worker stopped); please try again"

Counts = dict[str, int]


def _zero() -> Counts:
    return {"expired": 0, "stuck_failed": 0, "errors": 0}


async def _expire_tenant(settings: Settings, schema: str, now: datetime, counts: Counts) -> None:
    cutoff = now - timedelta(days=settings.export_retention_days)
    while True:
        async with tenant_session(schema) as ts:
            batch = (
                await ts.scalars(
                    select(ExportJob)
                    .where(ExportJob.status == "done", ExportJob.finished_at < cutoff)
                    .order_by(ExportJob.finished_at, ExportJob.id)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not batch:
                return
            for job in batch:
                if job.object_key:
                    try:
                        await storage.delete(settings, job.object_key)
                    except storage.StorageError:
                        counts["errors"] += 1
                        await ts.commit()  # keep what is already expired
                        return
                job.status, job.object_key = "expired", None
                counts["expired"] += 1
            await ts.commit()
        if len(batch) < BATCH_SIZE:
            return


async def _fail_stuck(schema: str, now: datetime, counts: Counts) -> None:
    async with tenant_session(schema) as ts:
        stuck = (
            await ts.scalars(
                select(ExportJob)
                .where(
                    ExportJob.status.in_(("queued", "running")),
                    ExportJob.created_at < now - STUCK_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        for job in stuck:
            job.status, job.error, job.finished_at = "failed", STUCK_ERROR, now
            notify(
                ts,
                job.requested_by,
                "export.failed",
                f"Your {job.resource} export failed",
                body=STUCK_ERROR,
                data={"export_id": str(job.id), "resource": job.resource, "format": job.format},
            )
            log.warning("exports.stuck_failed", export_id=str(job.id))
        counts["stuck_failed"] += len(stuck)
        await ts.commit()


async def expire_exports(
    settings: Settings,
    org_slug: str | None = None,
    now: datetime | None = None,
    actor: str = "worker",
) -> dict[str, Counts]:
    """Clean every eligible tenant (or just `org_slug`, NotFound if unknown)."""
    now = now or datetime.now(UTC)
    result: dict[str, Counts] = {}
    for slug, schema in await cleanup_tenants(org_slug):
        counts = _zero()
        try:
            if settings.export_retention_days > 0:
                await _expire_tenant(settings, schema, now, counts)
            await _fail_stuck(schema, now, counts)
        except Exception as exc:
            log.error(
                "exports.cleanup_tenant_failed",
                org=slug,
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            counts["errors"] += 1
        result[slug] = counts
        log.info("exports.cleanup_tenant", org=slug, **counts)
        if any(counts.values()):  # quiet days leave no audit noise (as J04)
            audit.record(
                "exports.expire",
                entity="export",
                org=slug,
                actor=actor,
                diff=counts,
                result="ok" if counts["errors"] == 0 else "error",
            )
    return result
