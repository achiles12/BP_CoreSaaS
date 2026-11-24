"""B13: `init` (migrate, sync, seed) and the demo seed (design B13 D7, D8)."""

import asyncio
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from click.testing import CliRunner, Result
from testcontainers.postgres import PostgresContainer

from app.cli import cli
from app.config import get_settings
from app.core import migrations
from app.modules.organizations import demo_seed as demo
from tests.conftest import create_database

pytestmark = pytest.mark.integration

Run = Callable[..., Result]
USERS = "select id, email, password_hash, is_active, is_verified from users order by email"


@pytest.fixture
def db_url(pg_container: PostgresContainer) -> str:
    """A fresh, empty database per test (init starts from nothing)."""
    return create_database(pg_container, f"b13_{uuid.uuid4().hex[:12]}")


@pytest.fixture
def run(db_url: str, audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Run]:
    for k, v in {
        "DATABASE_URL": db_url,
        "AUDIT_LOG_DIR": str(audit_dir),
        "CLI_USER": "init",
        "APP_ENV": "dev",
        "SEED_DEMO": "true",
    }.items():
        monkeypatch.setenv(k, v)

    def invoke(*args: str) -> Result:
        get_settings.cache_clear()
        return CliRunner().invoke(cli, list(args), catch_exceptions=False)

    yield invoke
    get_settings.cache_clear()


def sql(url: str, query: str, *args: Any) -> list[asyncpg.Record]:
    async def go() -> list[asyncpg.Record]:
        c = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            return await c.fetch(query, *args)
        finally:
            await c.close()

    return asyncio.run(go())


def test_init_on_empty_database(run: Run, db_url: str) -> None:
    r = run("init")
    assert r.exit_code == 0, r.output
    assert demo.DEMO_PASSWORD in r.output
    org = sql(db_url, "select status, name from organizations where slug='demo'")
    assert [(o["status"], o["name"]) for o in org] == [("active", "Demo Org")]
    users = sql(db_url, USERS)
    assert {u["email"] for u in users} == {*demo.DEMO_MEMBERS, demo.DEMO_PLATFORM}
    assert len(users) == 6 and all(u["is_active"] and u["is_verified"] for u in users)
    roles = sql(
        db_url,
        "select u.email, r.key from tenant_demo.user_roles ur "
        "join tenant_demo.roles r on r.id = ur.role_id join users u on u.id = ur.user_id",
    )
    assert sorted((r["email"], r["key"]) for r in roles) == sorted(
        (email, role) for email, (role, _) in demo.DEMO_MEMBERS.items()
    )
    p = sql(
        db_url,
        "select is_platform_admin, (select count(*) from org_memberships m where m.user_id=u.id) n "
        "from users u where email=$1",
        demo.DEMO_PLATFORM,
    )[0]
    assert p["is_platform_admin"] and p["n"] == 0


def test_init_twice_changes_nothing(run: Run, db_url: str) -> None:
    run("init")
    before = sql(db_url, USERS)
    r = run("init")
    assert r.exit_code == 0, r.output
    assert sql(db_url, USERS) == before


def test_seed_keeps_changed_user(run: Run, db_url: str) -> None:
    run("init")
    sql(
        db_url,
        "update users set password_hash='changed', is_active=false where email=$1",
        "staff@demo.test",
    )
    assert run("init").exit_code == 0
    u = sql(db_url, "select password_hash, is_active from users where email='staff@demo.test'")[0]
    assert (u["password_hash"], u["is_active"]) == ("changed", False)


def test_seed_keeps_removed_member_and_changed_role(run: Run, db_url: str) -> None:
    """Existing users are left alone: role changes and removals survive an `up`."""
    run("init")
    sql(
        db_url,
        "delete from tenant_demo.user_roles ur using users u "
        "where ur.user_id=u.id and u.email='user@demo.test'",
    )
    sql(
        db_url,
        "delete from org_memberships m using users u "
        "where m.user_id=u.id and u.email='user@demo.test'",
    )
    assert run("init").exit_code == 0
    n = sql(
        db_url,
        "select count(*) n from org_memberships m join users u on u.id=m.user_id "
        "where u.email='user@demo.test'",
    )[0]["n"]
    assert n == 0


@pytest.mark.parametrize("env", [{"SEED_DEMO": "false"}, {"APP_ENV": "test"}])
def test_init_skips_seed(
    run: Run, db_url: str, monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = run("init")
    assert r.exit_code == 0, r.output
    assert demo.DEMO_PASSWORD not in r.output
    assert sql(db_url, "select 1 from organizations") == []


def test_seed_demo_refused_outside_dev(
    run: Run, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run("migrate-all")
    monkeypatch.setenv("APP_ENV", "test")
    assert run("seed-demo").exit_code == 1
    assert sql(db_url, "select 1 from organizations") == []


@pytest.mark.parametrize("kind", ["slug", "suspended", "email"])
def test_init_survives_seed_conflict(run: Run, db_url: str, kind: str) -> None:
    run("migrate-all")
    if kind == "slug":
        run("create-tenant", "--slug", "demo", "--name", "Other Org", "--owner-email", "o@x.test")
    elif kind == "suspended":
        run("init")
        run("suspend-org", "--slug", "demo")
    else:
        run("create-tenant", "--slug", "other", "--name", "Other", "--owner-email", "o@x.test")
        sql(
            db_url,
            "with u as (insert into users (email, password_hash, is_verified) "
            "values ('staff@demo.test', 'keep', true) returning id) "
            "insert into org_memberships (user_id, org_id, status) "
            "select u.id, o.id, 'active' from u, organizations o where o.slug='other'",
        )
    before = sql(db_url, "select * from organizations order by slug")
    r = run("init")
    assert r.exit_code == 0, r.output
    assert "warning" in r.output.lower()
    assert ("staff@demo.test" if kind == "email" else "demo") in r.output
    after = {o["slug"]: o for o in sql(db_url, "select * from organizations")}
    for o in before:
        assert after[o["slug"]] == o
    if kind == "email":
        u = sql(
            db_url,
            "select u.password_hash, o.slug from users u join org_memberships m on m.user_id=u.id "
            "join organizations o on o.id=m.org_id where u.email='staff@demo.test'",
        )
        assert [(x["password_hash"], x["slug"]) for x in u] == [("keep", "other")]
    # The same conflict is an error when seeding is asked for explicitly.
    if kind != "email":
        assert run("seed-demo").exit_code == 1


def test_init_fails_when_a_tenant_migration_fails(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("init").exit_code == 0

    async def boom(schema: str) -> str:
        raise RuntimeError("planted")

    monkeypatch.setattr(migrations, "upgrade_tenant", boom)
    r = run("init")
    assert r.exit_code == 1
    assert "demo: FAILED" in r.output


def test_seed_audits_without_password(run: Run, audit_dir: Path) -> None:
    run("init")
    raw = (audit_dir / "audit.log").read_text()
    assert demo.DEMO_PASSWORD not in raw
    lines = [json.loads(x) for x in raw.splitlines()]
    created = [a for a in lines if a["action"] == "user.created"]
    emails = {a["diff"]["email"] for a in created}
    assert emails >= ({*demo.DEMO_MEMBERS, demo.DEMO_PLATFORM} - {"owner@demo.test"})
    assert all(a["actor"] == "cli:init" for a in created)
    assert any(a["action"] == "org.created" and a["org"] == "demo" for a in lines)


def _prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {
        "APP_ENV": "prod",
        "SECRET_KEY": "z" * 48,
        "COOKIE_SECURE": "true",
        "S3_ACCESS_KEY": "prod-access",
        "S3_SECRET_KEY": "prod-secret-value",
    }.items():
        monkeypatch.setenv(k, v)


def test_init_refuses_prod_while_the_demo_password_works(
    run: Run, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review I2: a demo'd database must not go live with a public password."""
    assert run("init").exit_code == 0
    _prod_env(monkeypatch)
    r = run("init")
    assert r.exit_code == 1
    assert demo.DEMO_PLATFORM in r.output and "staff@demo.test" in r.output
    # Deactivated users and changed passwords are fine.
    sql(db_url, "update users set is_active = false where email <> 'owner@demo.test'")
    r = run("init")
    assert r.exit_code == 1 and demo.DEMO_PLATFORM not in r.output
    sql(db_url, "update users set password_hash = 'changed' where email = 'owner@demo.test'")
    assert run("init").exit_code == 0


def test_init_in_prod_without_demo_users(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    _prod_env(monkeypatch)
    assert run("init").exit_code == 0
