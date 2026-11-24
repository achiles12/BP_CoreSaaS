"""C8: tenant provisioning end to end, through the CLI (B12 D7).

Runs on a database created for this module only, so "empty database" is
literal: public migrations, then create-tenant, as an operator would.
"""

import asyncio
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from testcontainers.postgres import PostgresContainer

from app.cli import cli
from app.config import get_settings
from app.core import db, migrations
from app.modules.organizations import provisioning
from app.modules.rbac.seed import DEFAULT_GRANTS
from tests.b04_helpers import sql
from tests.conftest import create_database
from tests.test_migrations import TENANT_HEAD

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def fresh_db(pg_container: PostgresContainer) -> str:
    return create_database(pg_container, f"b12prov{uuid.uuid4().hex[:6]}")


@pytest.fixture
def run(
    fresh_db: str, audit_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., Result]]:
    monkeypatch.setenv("DATABASE_URL", fresh_db)
    monkeypatch.setenv("AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("FRONTEND_URL", "http://lan-host:3200")
    monkeypatch.setenv("CLI_USER", "b12-provisioning")
    get_settings.cache_clear()
    runner = CliRunner()

    def invoke(*args: str) -> Result:
        return runner.invoke(cli, list(args), catch_exceptions=False)

    assert invoke("migrate-public").exit_code == 0
    yield invoke
    get_settings.cache_clear()


def actions(audit_dir: Path) -> list[str]:
    f = audit_dir / "audit.log"
    return [json.loads(x)["action"] for x in f.read_text().splitlines()] if f.exists() else []


def org(url: str, slug: str) -> dict:
    rows = sql(url, "select status, schema_name from organizations where slug=$1", slug)
    assert rows, f"no organization {slug!r}"
    return dict(rows[0])


def schema_exists(url: str, schema: str) -> bool:
    return bool(sql(url, "select 1 from information_schema.schemata where schema_name=$1", schema))


def slug() -> str:
    return f"prov{uuid.uuid4().hex[:6]}"


def test_create_tenant_from_nothing(
    run: Callable[..., Result], fresh_db: str, audit_dir: Path
) -> None:
    s = slug()
    r = run("create-tenant", "--slug", s, "--name", "Prov Org", "--owner-email", f"owner@{s}.test")
    assert r.exit_code == 0, r.output
    o = org(fresh_db, s)
    assert o == {"status": "active", "schema_name": f"tenant_{s}"}
    schema = f'"tenant_{s}"'
    # schema at head, roles, every registered permission, the default grants
    rev = sql(fresh_db, f"select version_num from {schema}.alembic_version_tenant")[0][0]  # noqa: S608
    assert rev == TENANT_HEAD
    roles = {r["key"] for r in sql(fresh_db, f"select key from {schema}.roles")}  # noqa: S608
    assert roles == {"owner", "admin", "manager", "staff", "user"}
    grants = sql(
        fresh_db,
        f"select r.key as role, p.key as perm from {schema}.role_permissions rp "  # noqa: S608
        f"join {schema}.roles r on r.id = rp.role_id "
        f"join {schema}.permissions p on p.id = rp.permission_id",
    )
    got: dict[str, set[str]] = {}
    for g in grants:
        got.setdefault(g["role"], set()).add(g["perm"])
    assert got == {k: set(v) for k, v in DEFAULT_GRANTS.items() if v}
    # an owner exists (invited, since no password was given)
    inv = sql(
        fresh_db,
        "select role_key from invitations i join organizations o on o.id=i.org_id where o.slug=$1",
        s,
    )
    assert [i["role_key"] for i in inv] == ["owner"]
    assert "org.created" in actions(audit_dir)


def test_second_run_is_a_no_op(run: Callable[..., Result], fresh_db: str) -> None:
    s = slug()
    args = ("create-tenant", "--slug", s, "--name", "Twice", "--owner-email", f"o@{s}.test")
    assert run(*args).exit_code == 0

    def counts() -> tuple:
        q = f'select (select count(*) from "tenant_{s}".roles), (select count(*) from invitations)'  # noqa: S608
        return tuple(sql(fresh_db, q)[0])

    before = counts()
    again = run(*args)
    assert again.exit_code == 0 and "already" in again.output.lower(), again.output
    assert counts() == before


def test_failed_run_leaves_no_half_tenant_and_resumes(
    run: Callable[..., Result], fresh_db: str, audit_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = slug()
    args = ("create-tenant", "--slug", s, "--name", "Broken", "--owner-email", f"o@{s}.test")

    async def boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("seed failed (injected)")

    monkeypatch.setattr(provisioning, "seed_tenant", boom)
    failed = run(*args)
    assert failed.exit_code == 1 and "injected" in failed.output, failed.output
    assert org(fresh_db, s)["status"] == "failed"
    assert not schema_exists(fresh_db, f"tenant_{s}"), "a failed run left its schema behind"
    assert "org.provision_failed" in actions(audit_dir)

    monkeypatch.undo()  # the real seed again
    monkeypatch.setenv("DATABASE_URL", fresh_db)
    monkeypatch.setenv("AUDIT_LOG_DIR", str(audit_dir))
    get_settings.cache_clear()
    r = run(*args)
    assert r.exit_code == 0, r.output
    assert org(fresh_db, s)["status"] == "active"
    assert schema_exists(fresh_db, f"tenant_{s}")


def test_migrate_all_brings_an_old_tenant_to_head(
    run: Callable[..., Result], fresh_db: str
) -> None:
    s = slug()
    assert (
        run("create-tenant", "--slug", s, "--name", "Old", "--owner-email", f"o@{s}.test").exit_code
        == 0
    )

    async def hold_back() -> None:  # as if it was created before B06/B07
        db.init_engine(fresh_db)
        try:
            await migrations.downgrade_tenant(f"tenant_{s}", "0002_files")
        finally:
            await db.dispose_engine()

    asyncio.run(hold_back())

    def rev() -> str:
        q = f'select version_num from "tenant_{s}".alembic_version_tenant'  # noqa: S608
        return sql(fresh_db, q)[0][0]

    assert rev() == "0002_files"
    r = run("migrate-all")
    assert r.exit_code == 0, r.output
    assert f"{s}: 0002_files -> {TENANT_HEAD} ok" in r.output
    assert rev() == TENANT_HEAD
