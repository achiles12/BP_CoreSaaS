"""B05: J04 cleanup_orphan_files (design D12, §3.5; review focus 5).

Uses the B04 world database (tenants acme4 + beta4) and the session RustFS.
Rows are inserted with SQL so their age can be set directly.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import text

from app.config import Settings, get_settings
from app.core import db, storage
from app.modules.files.cleanup import BATCH_SIZE, PENDING_MAX_AGE, purge_orphan_files
from app.worker import jobs
from app.worker.settings import WorkerSettings
from tests.conftest import B04World

pytestmark = pytest.mark.integration


def actions(audit_dir: Path, action: str) -> list[dict]:
    f = audit_dir / "audit.log"
    lines = [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []
    return [a for a in lines if a["action"] == action]


@pytest.fixture
async def engine(b05_settings: Settings, audit_log: Path) -> AsyncIterator[None]:
    db.init_engine(b05_settings.database_url)
    yield
    await db.dispose_engine()


async def add_file(
    settings: Settings, slug: str, status: str, age: timedelta, *, with_object: bool = True
) -> tuple[uuid.UUID, str]:
    fid = uuid.uuid4()
    key = f"{slug}/2026/11/{fid}"
    if with_object:
        url, headers = await storage.presign_put(settings, key, "text/plain")
        import httpx

        async with httpx.AsyncClient() as c:
            assert (await c.put(url, content=b"hello", headers=headers)).status_code == 200
    async with db.get_engine().begin() as c:
        uid = await c.scalar(
            text("select id from public.users where email=:e"), {"e": f"owner@{slug}.test"}
        )
        await c.execute(
            text(
                f"insert into tenant_{slug}.files "  # noqa: S608 (test slug)
                "(id, name, mime_type, size_bytes, object_key, status, uploaded_by, created_at) "
                "values (:id, 'x.txt', 'text/plain', 5, :k, :st, :u, :ts)"
            ),
            {"id": fid, "k": key, "st": status, "u": uid, "ts": datetime.now(UTC) - age},
        )
    return fid, key


async def exists(slug: str, fid: uuid.UUID) -> bool:
    async with db.get_engine().connect() as c:
        return bool(
            await c.scalar(
                text(f"select count(*) from tenant_{slug}.files where id=:i"),  # noqa: S608
                {"i": fid},
            )
        )


async def test_purges_old_pending_and_deleted_only(
    b05_settings: Settings, engine: None, audit_log: Path
) -> None:
    s = b05_settings
    await purge_orphan_files(s)  # start from a clean slate (other tests leave rows behind)
    old_pending = await add_file(s, "acme4", "pending", PENDING_MAX_AGE + timedelta(minutes=5))
    fresh_pending = await add_file(s, "acme4", "pending", timedelta(hours=1))
    deleted = await add_file(s, "acme4", "deleted", timedelta(minutes=1))
    deleted_no_obj = await add_file(s, "acme4", "deleted", timedelta(days=3), with_object=False)
    active = await add_file(s, "acme4", "active", timedelta(days=30))
    beta_deleted = await add_file(s, "beta4", "deleted", timedelta(days=1))

    counts = await purge_orphan_files(s)
    assert counts["acme4"] == {"pending_purged": 1, "deleted_purged": 2, "errors": 0}
    assert counts["beta4"] == {"pending_purged": 0, "deleted_purged": 1, "errors": 0}

    for fid, key in (old_pending, deleted, deleted_no_obj):
        assert not await exists("acme4", fid)
        assert await storage.head(s, key) is None
    assert not await exists("beta4", beta_deleted[0])
    for fid, key in (fresh_pending, active):
        assert await exists("acme4", fid)
        assert await storage.head(s, key) is not None

    purge = {a["org"]: a for a in actions(audit_log.parent, "files.purge")}
    assert purge["acme4"]["diff"] == {"pending_purged": 1, "deleted_purged": 2, "errors": 0}
    assert purge["acme4"]["actor"] == "worker"

    # idempotent: nothing left to do, no new audit lines
    n_audit = len(actions(audit_log.parent, "files.purge"))
    again = await purge_orphan_files(s)
    assert all(c == {"pending_purged": 0, "deleted_purged": 0, "errors": 0} for c in again.values())
    assert len(actions(audit_log.parent, "files.purge")) == n_audit


async def test_one_org_only(b05_settings: Settings, engine: None) -> None:
    a = await add_file(b05_settings, "acme4", "deleted", timedelta(hours=1))
    b = await add_file(b05_settings, "beta4", "deleted", timedelta(hours=1))
    counts = await purge_orphan_files(b05_settings, org_slug="beta4")
    assert set(counts) == {"beta4"}
    assert await exists("acme4", a[0]) and not await exists("beta4", b[0])
    await purge_orphan_files(b05_settings, org_slug="acme4")


async def test_more_than_one_batch(b05_settings: Settings, engine: None) -> None:
    await purge_orphan_files(b05_settings, org_slug="beta4")
    n = BATCH_SIZE + 3
    for _ in range(n):
        await add_file(b05_settings, "beta4", "deleted", timedelta(hours=1), with_object=False)
    counts = await purge_orphan_files(b05_settings, org_slug="beta4")
    assert counts["beta4"]["deleted_purged"] == n


async def test_broken_tenant_does_not_stop_the_others(
    b05_settings: Settings, engine: None, b04_world: B04World
) -> None:
    """Review focus 5: a schema without `files` -> errors:1, the rest still run."""
    async with db.get_engine().begin() as c:
        await c.execute(text("create schema if not exists tenant_b5broken"))
        await c.execute(
            text(
                "insert into public.organizations (name, slug, schema_name, status) "
                "values ('Broken', 'b5broken', 'tenant_b5broken', 'active') on conflict do nothing"
            )
        )
    d = await add_file(b05_settings, "beta4", "deleted", timedelta(hours=1))
    try:
        counts = await purge_orphan_files(b05_settings)
        assert counts["b5broken"]["errors"] == 1
        assert not await exists("beta4", d[0])
    finally:
        async with db.get_engine().begin() as c:
            await c.execute(text("delete from public.organizations where slug='b5broken'"))
            await c.execute(text("drop schema tenant_b5broken"))


async def test_storage_down_keeps_rows(b05_settings: Settings, engine: None) -> None:
    fid, _ = await add_file(b05_settings, "beta4", "deleted", timedelta(hours=1))
    down = b05_settings.model_copy(update={"s3_endpoint": "http://127.0.0.1:1"})
    counts = await purge_orphan_files(down, org_slug="beta4")
    assert counts["beta4"]["errors"] == 1 and counts["beta4"]["deleted_purged"] == 0
    assert await exists("beta4", fid)  # retried by the next run
    await purge_orphan_files(b05_settings, org_slug="beta4")


def test_worker_cron_registered() -> None:
    crons = {c.name: c for c in WorkerSettings.cron_jobs}
    j04 = crons["cron:cleanup_orphan_files"]
    assert j04.hour == {3} and j04.minute == {30}
    names = {getattr(f, "name", getattr(f, "__name__", "")) for f in WorkerSettings.functions}
    assert "cleanup_orphan_files" in names
    assert callable(jobs.cleanup_orphan_files)


def test_cli_cleanup_files(
    b05_settings: Settings, monkeypatch: pytest.MonkeyPatch, audit_dir: Path
) -> None:
    from app.cli import cli

    for k, v in {
        "DATABASE_URL": b05_settings.database_url,
        "AUDIT_LOG_DIR": str(audit_dir),
        "S3_ENDPOINT": b05_settings.s3_endpoint,
        "S3_PUBLIC_ENDPOINT": b05_settings.s3_public_endpoint,
        "S3_ACCESS_KEY": b05_settings.s3_access_key,
        "S3_SECRET_KEY": b05_settings.s3_secret_key,
        "S3_BUCKET": b05_settings.s3_bucket,
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        r = CliRunner().invoke(cli, ["cleanup-files", "--org", "beta4"], catch_exceptions=False)
        assert r.exit_code == 0, r.output
        assert "beta4: pending " in r.output and "errors 0" in r.output
        r = CliRunner().invoke(cli, ["cleanup-files", "--org", "nosuch"], catch_exceptions=False)
        assert r.exit_code == 1
    finally:
        get_settings.cache_clear()
