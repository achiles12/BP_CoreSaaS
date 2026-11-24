"""B07: export retention cleanup (design D2, D17; review focus 5).

Rows are inserted with SQL so their age can be set directly; objects are real
RustFS objects (session container).
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from sqlalchemy import text

from app.config import Settings
from app.core import db, storage
from app.modules.exports.cleanup import STUCK_AFTER, expire_exports
from app.worker import jobs
from app.worker.settings import WorkerSettings
from tests.conftest import B04World

pytestmark = pytest.mark.integration
SCHEMA = "tenant_acme4"


@pytest.fixture
async def engine(b05_settings: Settings, audit_log: Path) -> AsyncIterator[None]:
    db.init_engine(b05_settings.database_url)
    async with db.get_engine().begin() as c:  # each test sees only its own jobs
        await c.execute(text(f"delete from {SCHEMA}.export_jobs"))  # noqa: S608
    yield
    await db.dispose_engine()


async def q(sql: str, **kw: Any) -> Any:
    async with db.get_engine().begin() as c:
        res = await c.execute(text(sql), kw)
        return res.all() if res.returns_rows else []


async def manager(world: B04World) -> uuid.UUID:
    return (await q("select id from public.users where email=:e", e=world.users["manager"]))[0][0]


async def add_job(
    settings: Settings, user: uuid.UUID, status: str, age: timedelta, *, with_object: bool = True
) -> tuple[uuid.UUID, str | None]:
    jid = uuid.uuid4()
    key = f"exports/acme4/2026/11/{jid}.csv" if status == "done" else None
    if key and with_object:
        p = Path(f"/tmp/{jid}.csv")  # noqa: S108 (test file, removed below)
        p.write_text("id\r\n")  # noqa: ASYNC240
        await storage.put_file(settings, key, p, "text/csv")
        p.unlink()  # noqa: ASYNC240
    when = datetime.now(UTC) - age
    await q(
        f"insert into {SCHEMA}.export_jobs "  # noqa: S608
        "(id, requested_by, resource, format, status, object_key, created_at, finished_at) "
        "values (:i, :u, 'items', 'csv', cast(:s as text), :k, cast(:t as timestamptz), "
        "case when cast(:s as text) in ('done','failed') then cast(:t as timestamptz) end)",
        i=jid,
        u=user,
        s=status,
        k=key,
        t=when,
    )
    return jid, key


async def row(jid: uuid.UUID) -> Any:
    return (await q(f"select * from {SCHEMA}.export_jobs where id=:i", i=jid))[0]  # noqa: S608


def audit(audit_dir: Path, action: str) -> list[dict]:
    f = audit_dir / "audit.log"
    return [
        x
        for x in (json.loads(line) for line in f.read_text().splitlines())
        if x["action"] == action
    ]


async def test_old_done_exports_expire(
    engine: None, b05_settings: Settings, b04_world: B04World, audit_dir: Path
) -> None:
    mgr = await manager(b04_world)
    old, old_key = await add_job(b05_settings, mgr, "done", timedelta(days=8))
    new, new_key = await add_job(b05_settings, mgr, "done", timedelta(days=6))
    assert old_key and new_key
    gone, _ = await add_job(b05_settings, mgr, "done", timedelta(days=9), with_object=False)

    result = await expire_exports(b05_settings, "acme4")

    assert result["acme4"] == {"expired": 2, "stuck_failed": 0, "errors": 0}
    r = await row(old)
    assert r.status == "expired" and r.object_key is None
    assert await storage.head(b05_settings, old_key) is None
    assert (await row(gone)).status == "expired"  # missing object counts as done
    assert (await row(new)).status == "done"
    assert await storage.head(b05_settings, new_key) is not None
    lines = [a for a in audit(audit_dir, "exports.expire") if a["org"] == "acme4"]
    assert lines[-1]["diff"] == {"expired": 2, "stuck_failed": 0, "errors": 0}
    # idempotent: a second run finds nothing and writes no audit line
    n = len(audit(audit_dir, "exports.expire"))
    assert (await expire_exports(b05_settings, "acme4"))["acme4"]["expired"] == 0
    assert len(audit(audit_dir, "exports.expire")) == n


async def test_retention_zero_keeps_files(
    engine: None, b05_settings: Settings, b04_world: B04World
) -> None:
    mgr = await manager(b04_world)
    jid, key = await add_job(b05_settings, mgr, "done", timedelta(days=400))
    assert key
    keep = b05_settings.model_copy(update={"export_retention_days": 0})
    assert (await expire_exports(keep, "acme4"))["acme4"]["expired"] == 0
    assert (await row(jid)).status == "done" and await storage.head(keep, key) is not None


async def test_stuck_jobs_fail_and_notify(
    engine: None, b05_settings: Settings, b04_world: B04World
) -> None:
    mgr = await manager(b04_world)
    stuck_q, _ = await add_job(b05_settings, mgr, "queued", STUCK_AFTER + timedelta(minutes=5))
    stuck_r, _ = await add_job(b05_settings, mgr, "running", STUCK_AFTER + timedelta(minutes=5))
    fresh, _ = await add_job(b05_settings, mgr, "running", timedelta(minutes=5))
    keep = b05_settings.model_copy(update={"export_retention_days": 0})  # stuck check still runs

    assert (await expire_exports(keep, "acme4"))["acme4"]["stuck_failed"] == 2
    for jid in (stuck_q, stuck_r):
        r = await row(jid)
        assert r.status == "failed" and "did not finish" in r.error and r.finished_at is not None
        n = await q(
            f"select type from {SCHEMA}.notifications where data->>'export_id'=:j",  # noqa: S608
            j=str(jid),
        )
        assert [x.type for x in n] == ["export.failed"]
    assert (await row(fresh)).status == "running"


async def test_all_tenants_and_cron(
    engine: None, b05_settings: Settings, b04_world: B04World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "get_settings", lambda: b05_settings)
    result = await jobs.cleanup_exports({"job_id": "c"})
    assert {"acme4", "beta4"} <= set(result)
    cron = {c.name: c for c in WorkerSettings.cron_jobs}
    c = next(v for k, v in cron.items() if "cleanup_exports" in k)
    assert c.hour == {b05_settings.export_cleanup_hour} and c.minute == {
        b05_settings.export_cleanup_minute
    }


def test_cli_cleanup_exports(
    b05_settings: Settings, monkeypatch: pytest.MonkeyPatch, audit_dir: Path
) -> None:
    from app import cli

    monkeypatch.setattr(cli, "get_settings", lambda: b05_settings)
    ok = CliRunner().invoke(cli.cli, ["cleanup-exports", "--org", "acme4"])
    assert ok.exit_code == 0, ok.output
    assert "acme4: expired" in ok.output
    bad = CliRunner().invoke(cli.cli, ["cleanup-exports", "--org", "nosuchorg"])
    assert bad.exit_code != 0
