"""B07: J02 build_export (design §3.5, D1, D5, D7, D13, D16, D17).

Runs the job body (`run_export`) directly against the B04 world database and
the session RustFS. The file must hold exactly the rows the list returns for
the same query: compared here with list_items(), the function behind GET /items.
"""

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import openpyxl
import pytest
from sqlalchemy import text

from app.config import Settings
from app.core import db, storage
from app.core.pagination import ListQuery, PageParams, parse_filters, parse_sort
from app.core.tenancy import tenant_session
from app.modules._template import service as items_service
from app.modules._template.models import TemplateItem
from app.modules.exports import builder
from app.worker import jobs
from app.worker.settings import WorkerSettings
from tests.conftest import B04World

pytestmark = pytest.mark.integration
SCHEMA = "tenant_acme4"


@pytest.fixture
async def engine(b05_settings: Settings, audit_log: Path) -> AsyncIterator[None]:
    db.init_engine(b05_settings.database_url)
    yield
    await db.dispose_engine()


def tag() -> str:
    return "ex" + "".join(chr(97 + b % 26) for b in uuid.uuid4().bytes[:6])


async def q(sql: str, **kw: Any) -> Any:
    async with db.get_engine().begin() as c:
        return (await c.execute(text(sql), kw)).all()


async def uid(world: B04World, who: str) -> uuid.UUID:
    return (await q("select id from public.users where email=:e", e=world.users[who]))[0][0]


async def add_item(
    owner: uuid.UUID, title: str, status: str = "open", desc: str | None = None
) -> uuid.UUID:
    return (
        await q(
            f"insert into {SCHEMA}._template_items (title, description, status, owner_id) "  # noqa: S608
            "values (:t, :d, :s, :o) returning id",
            t=title,
            d=desc,
            s=status,
            o=owner,
        )
    )[0][0]


async def add_job(
    requester: uuid.UUID,
    filters: dict,
    fmt: str = "csv",
    resource: str = "items",
    status: str = "queued",
) -> uuid.UUID:
    return (
        await q(
            f"insert into {SCHEMA}.export_jobs (requested_by, resource, format, filters, status) "  # noqa: S608
            "values (:u, :r, :f, cast(:fl as jsonb), :s) returning id",
            u=requester,
            r=resource,
            f=fmt,
            fl=json.dumps(filters),
            s=status,
        )
    )[0][0]


async def job(jid: uuid.UUID) -> Any:
    return (await q(f"select * from {SCHEMA}.export_jobs where id=:i", i=jid))[0]  # noqa: S608


async def notes(user: uuid.UUID, jid: uuid.UUID) -> list[Any]:
    return await q(
        f"select type, title, body, data from {SCHEMA}.notifications "  # noqa: S608
        "where user_id=:u and data->>'export_id' = :j",
        u=user,
        j=str(jid),
    )


async def fetch(settings: Settings, key: str) -> bytes:
    url = await storage.presign_get(settings, key, "x")
    async with httpx.AsyncClient() as c:
        return (await c.get(url)).content


def audit(audit_dir: Path, action: str) -> list[dict]:
    f = audit_dir / "audit.log"
    return [
        x
        for x in (json.loads(line) for line in f.read_text().splitlines())
        if x["action"] == action
    ]


async def list_ids(filters: dict[str, str]) -> list[str]:
    """What GET /items returns (all pages) for the same parameters."""
    lq = ListQuery(
        page=PageParams(page=1, page_size=100),
        order_by=parse_sort(items_service.ITEMS_LIST, filters.get("sort"), TemplateItem.id),
        where=parse_filters(
            items_service.ITEMS_LIST, {k: v for k, v in filters.items() if k.startswith("filter")}
        ),
    )
    async with tenant_session(SCHEMA) as ts:
        items, _ = await items_service.list_items(ts, filters.get("q"), lq)
    return [str(i.id) for i in items]


async def test_csv_has_the_list_rows(
    engine: None, b05_settings: Settings, b04_world: B04World, audit_dir: Path
) -> None:
    t = tag()
    owner = await uid(b04_world, "staff")
    for title, st in (
        ("alpha", "open"),
        ("gamma", "open"),
        ("beta", "done"),
        ("delta", "in_progress"),
    ):
        await add_item(owner, f"{t} {title}", st)
    filters = {"q": t, "filter[status]": "open,done", "sort": "-title"}
    mgr = await uid(b04_world, "manager")
    jid = await add_job(mgr, filters)

    assert await builder.run_export(b05_settings, "acme4", jid) == "done"

    row = await job(jid)
    assert row.status == "done" and row.row_count == 3 and row.finished_at is not None
    assert row.object_key == f"exports/acme4/{row.created_at:%Y/%m}/{jid}.csv"
    raw = await fetch(b05_settings, row.object_key)
    assert raw.startswith("﻿".encode())  # D16 BOM
    assert b"\r\n" in raw
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == [
        "id",
        "title",
        "description",
        "status",
        "owner_id",
        "owner_name",
        "created_at",
        "updated_at",
    ]
    assert [r[0] for r in rows[1:]] == await list_ids(filters)
    assert [r[1] for r in rows[1:]] == [f"{t} gamma", f"{t} beta", f"{t} alpha"]
    assert rows[1][5] == "Staff"

    n = await notes(mgr, jid)
    assert len(n) == 1 and n[0].type == "export.done" and "3 rows" in n[0].body
    assert n[0].data == {"export_id": str(jid), "resource": "items", "format": "csv"}
    fin = [a for a in audit(audit_dir, "exports.finish") if a["entity_id"] == str(jid)]
    assert len(fin) == 1 and fin[0]["result"] == "ok" and fin[0]["diff"]["row_count"] == 3


async def test_xlsx_same_rows_and_cells_are_safe(
    engine: None, b05_settings: Settings, b04_world: B04World
) -> None:
    t = tag()
    owner = await uid(b04_world, "staff")
    await add_item(owner, f"{t} Café ✓ naïve", desc="=cmd|' /C calc'!A0")
    await add_item(owner, f"{t} plain", desc="@SUM(1)")
    mgr = await uid(b04_world, "manager")
    filters = {"q": t, "sort": "title"}

    jid = await add_job(mgr, filters, fmt="xlsx")
    assert await builder.run_export(b05_settings, "acme4", jid) == "done"
    wb = openpyxl.load_workbook(io.BytesIO(await fetch(b05_settings, (await job(jid)).object_key)))
    ws = wb.active
    assert ws is not None
    vals = [list(r) for r in ws.iter_rows(values_only=True)]
    assert vals[0][:2] == ("id", "title") or vals[0][:2] == ["id", "title"]
    assert [v[0] for v in vals[1:]] == await list_ids(filters)
    assert vals[1][1] == f"{t} Café ✓ naïve"  # non-ASCII intact
    assert vals[1][2] == "'=cmd|' /C calc'!A0" and vals[2][2] == "'@SUM(1)"  # never a formula

    cid = await add_job(mgr, filters)
    assert await builder.run_export(b05_settings, "acme4", cid) == "done"
    text_ = (await fetch(b05_settings, (await job(cid)).object_key)).decode("utf-8-sig")
    assert f"{t} Café ✓ naïve" in text_ and "'=cmd|" in text_ and "'@SUM(1)" in text_


async def test_users_export_with_roles(
    engine: None, b05_settings: Settings, b04_world: B04World
) -> None:
    mgr = await uid(b04_world, "manager")
    jid = await add_job(mgr, {"q": "@acme4", "sort": "email"}, resource="users")
    assert await builder.run_export(b05_settings, "acme4", jid) == "done"
    rows = list(
        csv.reader(
            io.StringIO(
                (await fetch(b05_settings, (await job(jid)).object_key)).decode("utf-8-sig")
            )
        )
    )
    assert rows[0] == ["id", "email", "full_name", "status", "is_verified", "roles", "joined_at"]
    by_email = {r[1]: r for r in rows[1:]}
    assert by_email[b04_world.users["manager"]][5] == "manager"
    assert [r[1] for r in rows[1:]] == sorted(r[1] for r in rows[1:])


async def test_too_many_rows_fails_without_file(
    engine: None, b05_settings: Settings, b04_world: B04World, audit_dir: Path
) -> None:
    t = tag()
    owner = await uid(b04_world, "staff")
    for i in range(3):
        await add_item(owner, f"{t} {i}")
    mgr = await uid(b04_world, "manager")
    jid = await add_job(mgr, {"q": t})
    small = b05_settings.model_copy(update={"export_max_rows": 2})
    assert await builder.run_export(small, "acme4", jid) == "failed"
    row = await job(jid)
    assert row.status == "failed" and row.object_key is None
    assert row.error == "3 rows match, the limit is 2; narrow the filters"
    n = await notes(mgr, jid)
    assert [x.type for x in n] == ["export.failed"] and row.error in n[0].body
    fin = [a for a in audit(audit_dir, "exports.finish") if a["entity_id"] == str(jid)]
    assert fin[0]["result"] == "error"


async def test_requester_lost_permission_fails(
    engine: None, b05_settings: Settings, b04_world: B04World
) -> None:
    """Review focus 3: staff never had export:run; a job in their name must not run."""
    staff = await uid(b04_world, "staff")
    jid = await add_job(staff, {})
    assert await builder.run_export(b05_settings, "acme4", jid) == "failed"
    row = await job(jid)
    assert "export:run" in row.error and row.object_key is None
    assert [x.type for x in await notes(staff, jid)] == ["export.failed"]


async def test_only_queued_jobs_run(
    engine: None, b05_settings: Settings, b04_world: B04World
) -> None:
    mgr = await uid(b04_world, "manager")
    for st in ("running", "done", "failed", "expired"):
        jid = await add_job(mgr, {}, status=st)
        assert await builder.run_export(b05_settings, "acme4", jid) == st
        assert (await job(jid)).status == st and await notes(mgr, jid) == []
    assert await builder.run_export(b05_settings, "acme4", uuid.uuid4()) == "missing"
    assert await builder.run_export(b05_settings, "nosuchorg", uuid.uuid4()) == "missing"


async def test_storage_failure_marks_failed_and_cleans_temp(
    engine: None,
    b05_settings: Settings,
    b04_world: B04World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp = tmp_path / "exports-tmp"
    tmp.mkdir()
    monkeypatch.setattr(builder.tempfile, "tempdir", str(tmp))
    mgr = await uid(b04_world, "manager")
    jid = await add_job(mgr, {})
    down = b05_settings.model_copy(update={"s3_endpoint": "http://127.0.0.1:1"})
    assert await builder.run_export(down, "acme4", jid) == "failed"
    assert "storage" in (await job(jid)).error.lower()
    assert list(tmp.iterdir()) == []


async def test_job_wrapper_and_worker_registration(
    engine: None, b05_settings: Settings, b04_world: B04World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "get_settings", lambda: b05_settings)
    mgr = await uid(b04_world, "manager")
    jid = await add_job(mgr, {})
    assert await jobs.build_export({"job_id": "t"}, str(jid), "acme4") == "done"
    fn = {f.name: f for f in WorkerSettings.functions if hasattr(f, "name")}
    assert fn["build_export"].max_tries == 1
