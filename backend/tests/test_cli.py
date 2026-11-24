"""T12: CLI commands through click's CliRunner (design B02 §3.10).

Sync tests on purpose: each command runs its own asyncio.run(), exactly as in
the container. Settings come from env vars, as in production.
"""

import itertools
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from app.cli import cli
from app.config import get_settings
from tests.test_migrations import TENANT_HEAD

pytestmark = pytest.mark.integration

STRONG = "cli-strong-pass-123"
_n = itertools.count(1)


@pytest.fixture
def run(b02_db_url: str, audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:  # noqa: ANN001
    monkeypatch.setenv("DATABASE_URL", b02_db_url)
    monkeypatch.setenv("AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("FRONTEND_URL", "http://lan-host:3200")
    monkeypatch.setenv("CLI_USER", "pytest-operator")
    get_settings.cache_clear()
    runner = CliRunner()

    def invoke(*args: str, input: str | None = None) -> Result:  # noqa: A002
        return runner.invoke(cli, list(args), input=input, catch_exceptions=False)

    assert invoke("migrate-public").exit_code == 0
    yield invoke
    get_settings.cache_clear()


def slug() -> str:
    return f"cli_{next(_n):03d}"


def audit_actions(audit_dir: Path) -> list[dict]:
    f = audit_dir / "audit.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_help_lists_commands(run) -> None:  # noqa: ANN001
    out = run("--help").output
    for cmd in (
        "create-tenant",
        "migrate-public",
        "migrate-all",
        "list-orgs",
        "suspend-org",
        "activate-org",
        "sync-permissions",
        "rotate-secret-check",
        "create-user",
        "set-user-status",
    ):
        assert cmd in out


def test_create_tenant_prints_invite_link(run, audit_dir: Path) -> None:  # noqa: ANN001
    s = slug()
    r = run("create-tenant", "--slug", s, "--name", "Cli Org", "--owner-email", f"o@{s}.test")
    assert r.exit_code == 0, r.output
    assert f"{s}: created, schema tenant_{s}" in r.output
    # 15 keys up to B05 + items:read/write/delete from the template module (B06)
    assert "seeded: 5 roles, 18 permissions" in r.output
    assert "owner" in r.output and "invited" in r.output
    assert "http://lan-host:3200/accept-invite?token=" in r.output
    entry = [a for a in audit_actions(audit_dir) if a["action"] == "org.created"][-1]
    assert entry["actor"] == "cli:pytest-operator" and entry["org"] == s

    again = run("create-tenant", "--slug", s, "--name", "Cli Org", "--owner-email", f"o@{s}.test")
    assert again.exit_code == 0 and "already active" in again.output


def test_create_tenant_with_password_prompt(run) -> None:  # noqa: ANN001
    s = slug()
    r = run(
        "create-tenant",
        "--slug",
        s,
        "--name",
        "P",
        "--owner-email",
        f"o@{s}.test",
        "--owner-password",
        input=f"{STRONG}\n{STRONG}\n",
    )
    assert r.exit_code == 0, r.output
    assert "owner" in r.output and ": created" in r.output.split("owner", 1)[1]
    assert STRONG not in r.output  # hidden input, never echoed
    assert "accept-invite" not in r.output


def test_password_mismatch_then_weak_password(run) -> None:  # noqa: ANN001
    s = slug()
    # click re-prompts on mismatch; second attempt is weak -> rejected, exit 1.
    r = run(
        "create-tenant",
        "--slug",
        s,
        "--name",
        "P",
        "--owner-email",
        f"o@{s}.test",
        "--owner-password",
        input=f"{STRONG}\nother-one-123x\nshort\nshort\n",
    )
    assert "do not match" in r.output.lower()
    assert r.exit_code == 1 and "at least 12" in r.output


def test_bad_slug_exit_1(run) -> None:  # noqa: ANN001
    r = run("create-tenant", "--slug", "Bad Slug!", "--name", "X", "--owner-email", "a@b.c")
    assert r.exit_code == 1
    assert "slug must be" in r.output


def test_missing_option_is_usage_error(run) -> None:  # noqa: ANN001
    r = run("create-tenant", "--slug", "abc")
    assert r.exit_code == 2


def test_list_suspend_activate(run, audit_dir: Path) -> None:  # noqa: ANN001
    s = slug()
    run(
        "create-tenant",
        "--slug",
        s,
        "--name",
        "Listed",
        "--owner-email",
        f"o@{s}.test",
        "--owner-password",
        input=f"{STRONG}\n{STRONG}\n",
    )
    out = run("list-orgs").output
    line = next(x for x in out.splitlines() if x.startswith(s))
    assert "active" in line and "tenant_" + s in line and "Listed" in line
    assert line.split()[2] == "1"  # one active member (the owner)

    r = run("suspend-org", "--slug", s)
    assert r.exit_code == 0 and "active -> suspended" in r.output
    assert "already suspended" in run("suspend-org", "--slug", s).output
    r = run("activate-org", "--slug", s)
    assert r.exit_code == 0 and "suspended -> active" in r.output
    actions = [a["action"] for a in audit_actions(audit_dir)]
    assert "org.suspended" in actions and "org.activated" in actions

    assert run("suspend-org", "--slug", "nosuch").exit_code == 1


def test_migrate_all_reports_each_tenant(run) -> None:  # noqa: ANN001
    s = slug()
    run("create-tenant", "--slug", s, "--name", "M", "--owner-email", f"o@{s}.test")
    r = run("migrate-all")
    assert r.exit_code == 0, r.output
    assert f"{s}: {TENANT_HEAD} -> {TENANT_HEAD} ok" in r.output
    assert "0 failed" in r.output


def test_migrate_all_exits_1_when_a_tenant_fails(
    run,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    s = slug()
    run("create-tenant", "--slug", s, "--name", "F", "--owner-email", f"o@{s}.test")
    import app.core.migrations as m

    real = m.upgrade_tenant

    async def flaky(schema: str):  # noqa: ANN202
        if schema == f"tenant_{s}":
            raise RuntimeError("broken tenant")
        return await real(schema)

    monkeypatch.setattr(m, "upgrade_tenant", flaky)
    r = run("migrate-all")
    assert r.exit_code == 1
    assert f"{s}: FAILED RuntimeError: broken tenant" in r.output
    # Other tenants were still migrated.
    assert " ok" in r.output


def test_sync_permissions(run) -> None:  # noqa: ANN001
    s = slug()
    run("create-tenant", "--slug", s, "--name", "S", "--owner-email", f"o@{s}.test")
    r = run("sync-permissions")
    assert r.exit_code == 0 and f"{s}: 0 new permission key(s)" in r.output


def test_rotate_secret_check_flags_dev_settings(run) -> None:  # noqa: ANN001
    r = run("rotate-secret-check")
    assert r.exit_code == 1
    assert "SECRET_KEY is the dev default" in r.output


def test_rotate_secret_check_passes_safe_settings(
    run,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    monkeypatch.setenv("SECRET_KEY", "z" * 48)
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("S3_ACCESS_KEY", "prod-access")
    monkeypatch.setenv("S3_SECRET_KEY", "prod-secret-value")
    get_settings.cache_clear()
    r = run("rotate-secret-check")
    assert r.exit_code == 0 and "passes production checks" in r.output


# --------------------------------------------------------------------------- #
# B03: create-user / set-user-status (design B03 §3.9, D16)
# --------------------------------------------------------------------------- #
USER_PW = "cli-user-pass-123"


def _sql(url: str, query: str, *args: object) -> list:
    import asyncio

    import asyncpg

    async def go() -> list:
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg", "postgresql"))
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


def _pw_input() -> str:
    return f"{USER_PW}\n{USER_PW}\n"


def test_create_user_verified_and_promote(run, b02_db_url: str, audit_dir: Path) -> None:  # noqa: ANN001
    email = f"plain{next(_n)}@cli.test"
    r = run("create-user", "--email", email.upper(), "--full-name", "Plain", input=_pw_input())
    assert r.exit_code == 0, r.output
    assert "created" in r.output and "verified" in r.output and USER_PW not in r.output
    row = _sql(
        b02_db_url,
        "select is_verified, is_platform_admin, is_active, "
        "left(password_hash, 10) h from users where email=$1",
        email,
    )[0]
    assert (row["is_verified"], row["is_platform_admin"], row["is_active"]) == (True, False, True)
    assert row["h"] == "$argon2id$"

    dup = run("create-user", "--email", email, input=_pw_input())
    assert dup.exit_code == 1 and "already exists" in dup.output

    promote = run("create-user", "--email", email, "--platform-admin")
    assert promote.exit_code == 0 and "promoted to platform admin" in promote.output
    assert _sql(b02_db_url, "select is_platform_admin from users where email=$1", email)[0][0]
    again = run("create-user", "--email", email, "--platform-admin")
    assert "already platform admin" in again.output

    acts = {(a["action"], a["actor"]) for a in audit_actions(audit_dir)}
    assert ("user.created", "cli:pytest-operator") in acts
    assert ("user.platform_admin_granted", "cli:pytest-operator") in acts
    assert USER_PW not in (audit_dir / "audit.log").read_text()


def test_create_platform_admin_directly(run, b02_db_url: str) -> None:  # noqa: ANN001
    email = f"padmin{next(_n)}@cli.test"
    r = run("create-user", "--email", email, "--platform-admin", input=_pw_input())
    assert r.exit_code == 0 and "platform admin" in r.output
    assert _sql(b02_db_url, "select is_platform_admin from users where email=$1", email)[0][0]


def test_create_user_rejects_weak_password_and_bad_email(run) -> None:  # noqa: ANN001
    r = run("create-user", "--email", f"weak{next(_n)}@cli.test", input="short\nshort\n")
    assert r.exit_code == 1 and "at least 12" in r.output
    r = run("create-user", "--email", "not-an-email")
    assert r.exit_code == 2 and "invalid email" in r.output


def test_create_user_send_verification(
    run,
    b02_db_url: str,
    redis_container,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    import asyncio

    from redis.asyncio import Redis

    from tests.conftest import redis_url

    monkeypatch.setenv("REDIS_URL", redis_url(redis_container))
    get_settings.cache_clear()

    async def queued() -> int:
        r = Redis.from_url(redis_url(redis_container))
        try:
            return await r.zcard("arq:queue")
        finally:
            await r.aclose()

    before = asyncio.run(queued())
    email = f"unv{next(_n)}@cli.test"
    r = run("create-user", "--email", email, "--send-verification", input=_pw_input())
    assert r.exit_code == 0, r.output
    assert "verification email queued" in r.output
    assert asyncio.run(queued()) == before + 1
    row = _sql(
        b02_db_url,
        "select u.is_verified, count(t.id) n from users u join "
        "email_verification_tokens t on t.user_id=u.id where u.email=$1 group by 1",
        email,
    )
    assert row[0]["is_verified"] is False and row[0]["n"] == 1


def test_set_user_status_revokes_sessions(run, b02_db_url: str, audit_dir: Path) -> None:  # noqa: ANN001
    email = f"status{next(_n)}@cli.test"
    run("create-user", "--email", email, input=_pw_input())
    uid = _sql(b02_db_url, "select id from users where email=$1", email)[0][0]
    for i in range(2):
        _sql(
            b02_db_url,
            "insert into refresh_tokens (user_id, family_id, token_hash, expires_at) "
            "values ($1, gen_random_uuid(), $2, now() + interval '1 day')",
            uid,
            f"h{uid}{i}",
        )

    r = run("set-user-status", "--email", email, "--inactive")
    assert r.exit_code == 0 and "inactive (2 session token(s) revoked)" in r.output
    assert _sql(b02_db_url, "select is_active from users where id=$1", uid)[0][0] is False
    assert (
        _sql(
            b02_db_url,
            "select count(*) from refresh_tokens where user_id=$1 and revoked_at is null",
            uid,
        )[0][0]
        == 0
    )
    assert "already inactive" in run("set-user-status", "--email", email, "--inactive").output
    assert run("set-user-status", "--email", email, "--active").exit_code == 0
    assert _sql(b02_db_url, "select is_active from users where id=$1", uid)[0][0] is True

    missing = run("set-user-status", "--email", "nobody@cli.test", "--active")
    assert missing.exit_code == 1 and "not found" in missing.output
    assert any(a["action"] == "user.status_changed" for a in audit_actions(audit_dir))


# --------------------------------------------------------------------------- #
# B04: invite-user, one-org-per-user in create-tenant
# --------------------------------------------------------------------------- #
def test_invite_user_cli(
    run,
    b02_db_url: str,
    redis_container,
    audit_dir: Path,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import redis_url

    monkeypatch.setenv("REDIS_URL", redis_url(redis_container))
    get_settings.cache_clear()
    s = slug()
    run("create-tenant", "--slug", s, "--name", "Inv", "--owner-email", f"o@{s}.test")
    email = f"inv{next(_n)}@cli.test"
    r = run("invite-user", "--org", s, "--email", email, "--role", "manager")
    assert r.exit_code == 0, r.output
    assert "as manager created" in r.output and "/accept-invite?token=" in r.output
    assert "email queued" in r.output and "NOT" not in r.output
    again = run("invite-user", "--org", s, "--email", email, "--role", "staff")
    assert "re-issued" in again.output
    row = _sql(
        b02_db_url, "select role_key from invitations where email=$1 and accepted_at is null", email
    )
    assert [x[0] for x in row] == ["staff"]
    assert (
        run("invite-user", "--org", "nope_org", "--email", email, "--role", "staff").exit_code == 1
    )
    bad = run("invite-user", "--org", s, "--email", f"x{email}", "--role", "boss")
    assert bad.exit_code == 1 and "unknown role" in bad.output
    assert any(
        a["action"] == "users.invite" and a["actor"] == "cli:pytest-operator"
        for a in audit_actions(audit_dir)
    )


def test_create_tenant_refuses_owner_from_other_org(run) -> None:  # noqa: ANN001
    s1, s2 = slug(), slug()
    pw = "owner-pass-12345\nowner-pass-12345\n"
    email = f"shared{next(_n)}@cli.test"
    assert (
        run(
            "create-tenant",
            "--slug",
            s1,
            "--name",
            "One",
            "--owner-email",
            email,
            "--owner-password",
            input=pw,
        ).exit_code
        == 0
    )
    r = run("create-tenant", "--slug", s2, "--name", "Two", "--owner-email", email)
    assert r.exit_code == 1 and "already a member of another organization" in r.output
