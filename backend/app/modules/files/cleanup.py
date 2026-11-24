"""J04 logic: remove orphaned and deleted file objects (design B05 D12, §3.5).

Shared by the arq cron job (worker/jobs.py, 03:30 UTC) and the CLI command
`cleanup-files`. For every active or suspended tenant:

1. pick rows that are `deleted`, or `pending` and older than PENDING_MAX_AGE
   (an upload URL lives 15 min, so a 24 h old pending row is abandoned)
2. delete each object from RustFS (a missing object counts as done)
3. hard-delete the rows whose object is gone, committing per batch

Each tenant runs in its own try/except, so one broken schema never stops the
others. If RustFS fails mid-batch, the rows not yet cleaned stay as they are
and the next run retries them. Idempotent: a second run finds nothing.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, or_, select

from app.config import Settings
from app.core import audit, db, storage
from app.core.errors import NotFound
from app.core.tenancy import tenant_session
from app.models.public import Organization
from app.models.tenant import File

log = structlog.get_logger("app.files.cleanup")

PENDING_MAX_AGE = timedelta(hours=24)
BATCH_SIZE = 500
# Provisioning/failed tenants may not have a (fully migrated) schema yet.
CLEANUP_ORG_STATUSES = ("active", "suspended")

Counts = dict[str, int]


def _zero() -> Counts:
    return {"pending_purged": 0, "deleted_purged": 0, "errors": 0}


async def _tenants(org_slug: str | None) -> list[tuple[str, str]]:
    """(slug, schema_name) of the tenants to clean. Unknown --org -> NotFound."""
    stmt = select(Organization.slug, Organization.schema_name).order_by(Organization.slug)
    if org_slug:
        stmt = stmt.where(Organization.slug == org_slug)
    else:
        stmt = stmt.where(Organization.status.in_(CLEANUP_ORG_STATUSES))
    async with db.get_session_factory()() as s:
        rows = [(str(r[0]), str(r[1])) for r in (await s.execute(stmt)).all()]
    if org_slug and not rows:
        raise NotFound(f"Organization {org_slug!r} not found")
    return rows


async def _purge_tenant(settings: Settings, slug: str, schema: str, now: datetime) -> Counts:
    counts = _zero()
    cutoff = now - PENDING_MAX_AGE
    orphan = or_(File.status == "deleted", (File.status == "pending") & (File.created_at < cutoff))
    while True:
        async with tenant_session(schema) as ts:
            batch = (
                await ts.execute(
                    select(File.id, File.object_key, File.status)
                    .where(orphan)
                    .order_by(File.id)
                    .limit(BATCH_SIZE)
                )
            ).all()
            if not batch:
                return counts
            done = []
            storage_failed = False
            for fid, key, status in batch:
                try:
                    await storage.delete(settings, key)
                except storage.StorageError:
                    # RustFS is down: stop this tenant. Already logged by storage.
                    counts["errors"] += 1
                    storage_failed = True
                    break
                done.append(fid)
                counts["pending_purged" if status == "pending" else "deleted_purged"] += 1
            # Rows whose object is already gone are removed even if a later
            # delete failed; the rest wait for the next run.
            if done:
                await ts.execute(delete(File).where(File.id.in_(done)))
                await ts.commit()
        if storage_failed or len(batch) < BATCH_SIZE:
            return counts


async def purge_orphan_files(
    settings: Settings,
    org_slug: str | None = None,
    now: datetime | None = None,
    actor: str = "worker",
) -> dict[str, Counts]:
    """Clean every eligible tenant (or just `org_slug`). Returns counts per slug.

    `actor` is "worker" for the cron job and "cli:<user>" for `cleanup-files`.
    """
    now = now or datetime.now(UTC)
    result: dict[str, Counts] = {}
    for slug, schema in await _tenants(org_slug):
        try:
            counts = await _purge_tenant(settings, slug, schema, now)
        except Exception as exc:
            # Per-tenant isolation (backend_processes.md J04): log, count, go on.
            log.error(
                "files.cleanup_tenant_failed", org=slug, error=f"{type(exc).__name__}: {exc}"[:500]
            )
            counts = _zero()
            counts["errors"] = 1
            # Purges done before the failure are already committed; not re-counted.
        result[slug] = counts
        log.info("files.cleanup_tenant", org=slug, **counts)
        if any(counts.values()):  # quiet days leave no audit noise
            audit.record(
                "files.purge",
                entity="file",
                org=slug,
                actor=actor,
                diff=counts,
                result="ok" if counts["errors"] == 0 else "error",
            )
    return result
