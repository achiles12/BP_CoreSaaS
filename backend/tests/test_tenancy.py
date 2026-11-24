"""T4 slugs, T5 seed, T6–T8 provisioning, T9 resolve, T10 isolation, T11 registry."""

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text

from app.core import db
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.permissions import PermissionDef, all_permissions, load_module_permissions, register
from app.core.security import hash_password, hash_token, verify_password
from app.core.tenancy import (
    TenantContext,
    resolve_tenant,
    schema_for,
    tenant_session,
    validate_slug,
)
from app.models.public import Invitation, Organization, OrgMembership, User
from app.models.tenant import Permission, Role, RolePermission, Setting, UserRole
from app.modules.organizations import provisioning
from app.modules.organizations.provisioning import provision_tenant
from app.modules.rbac.seed import DEFAULT_GRANTS, SYSTEM_ROLES

FRONTEND = "http://frontend.test:3200"
STRONG = "correct-horse-42-battery"


# ---------------------------------- T4 ------------------------------------- #
@pytest.mark.parametrize("ok", ["acme", "a_b", "abc123", "x" + "y" * 30, "  Acme  "])
def test_valid_slugs(ok: str) -> None:
    assert validate_slug(ok) == ok.strip().lower()


@pytest.mark.parametrize(
    "bad",
    [
        "ab",
        "1abc",
        "_abc",
        "ab-c",
        "abc def",
        "x" * 32,
        "",
        "acme;drop",
        "ac'me",
        "tenant",
        "public",
        "admin",
        "pg_catalog",
    ],
)
def test_invalid_or_reserved_slugs(bad: str) -> None:
    with pytest.raises(BadRequest):
        validate_slug(bad)


def test_schema_for() -> None:
    assert schema_for("acme") == "tenant_acme"


# ---------------------------------- T11 ------------------------------------ #
def test_registry_has_all_core_keys() -> None:
    keys = {d.key for d in load_module_permissions()}
    expected = {
        "users:read",
        "users:invite",
        "users:update",
        "users:deactivate",
        "roles:read",
        "roles:assign",
        "org:read",
        "org:update",
        "files:read",
        "files:write",
        "files:delete",
        "search:use",
        "export:run",
        "notifications:read",
        "platform:manage",
        # B06 template module (registered through app/modules/registry.py)
        "items:read",
        "items:write",
        "items:delete",
    }
    assert keys == expected


@pytest.mark.parametrize("bad", ["nocolon", "Files:read", "files:read:x", "files:", ":read"])
def test_registry_rejects_bad_keys(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid permission key"):
        register([PermissionDef(bad, "x")])


def test_registry_rejects_conflicting_duplicate() -> None:
    load_module_permissions()
    with pytest.raises(ValueError, match="registered twice"):
        register([PermissionDef("files:read", "a different description")])


def test_every_matrix_key_is_registered() -> None:
    registered = {d.key for d in load_module_permissions()}
    for role, keys in DEFAULT_GRANTS.items():
        assert keys <= registered, (role, keys - registered)
    assert all("platform:manage" not in keys for keys in DEFAULT_GRANTS.values())


# --------------------------------------------------------------------------- #
# Integration
# --------------------------------------------------------------------------- #
async def _provision(
    slug: str, *, email: str | None = None, password: str | None = None, name: str | None = None
) -> provisioning.ProvisionResult:
    return await provision_tenant(
        slug,
        name or slug.title(),
        email or f"owner@{slug}.test",
        owner_password=password,
        actor="cli:pytest",
        frontend_url=FRONTEND,
    )


def _audit_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


async def _org(slug: str) -> Organization | None:
    async with db.get_session_factory()() as s:
        return await s.scalar(select(Organization).where(Organization.slug == slug))


async def _schema_exists(schema: str) -> bool:
    async with db.get_engine().connect() as c:
        return bool(
            await c.scalar(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name=:s"),
                {"s": schema},
            )
        )


# ---------------------------------- T5 ------------------------------------- #
@pytest.mark.integration
async def test_seed_roles_permissions_grants_settings(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    slug = new_slug("seed")
    r = await _provision(slug)
    assert (r.seed.roles_added, r.seed.settings_added) == (5, 1)
    assert r.seed.permissions_added == len(all_permissions())
    async with tenant_session(r.schema_name) as s:
        roles = {x.key: x for x in (await s.scalars(select(Role))).all()}
        assert {k: (v.priority, v.landing_path, v.is_system) for k, v in roles.items()} == {
            d.key: (d.priority, d.landing_path, True) for d in SYSTEM_ROLES
        }
        rows = await s.execute(
            select(Role.key, Permission.key)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
        )
        actual: dict[str, set[str]] = {}
        for role_key, perm_key in rows:
            actual.setdefault(role_key, set()).add(perm_key)
        # The matrix must match system_design §4 EXACTLY, role by role.
        assert actual == {k: set(v) for k, v in DEFAULT_GRANTS.items()}
        setting = await s.scalar(select(Setting.value).where(Setting.key == "app.display_name"))
        assert setting == slug.title()


@pytest.mark.integration
async def test_reseed_is_noop_and_keeps_manual_grant_removal(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    from app.modules.rbac.seed import seed_tenant

    r = await _provision(new_slug("reseed"))
    async with tenant_session(r.schema_name) as s:
        staff = await s.scalar(select(Role.id).where(Role.key == "staff"))
        files_write = await s.scalar(select(Permission.id).where(Permission.key == "files:write"))
        # Operator removes a default grant in DBeaver.
        await s.execute(
            delete(RolePermission).where(
                RolePermission.role_id == staff, RolePermission.permission_id == files_write
            )
        )
    async with tenant_session(r.schema_name) as s:
        report = await seed_tenant(s, "whatever")
        assert (report.roles_added, report.permissions_added, report.grants_added) == (0, 0, 0)
        assert report.settings_added == 0
        still_removed = await s.scalar(
            select(func.count()).where(
                RolePermission.role_id == staff, RolePermission.permission_id == files_write
            )
        )
        assert still_removed == 0


# ------------------------------- T6 / T7 ----------------------------------- #
@pytest.mark.integration
async def test_provision_with_invitation(
    migrated: str, new_slug: Callable[[str], str], audit_log: Path
) -> None:
    slug = new_slug("inv")
    r = await _provision(slug)
    assert (r.outcome, r.owner_status) == ("created", "invited")
    assert r.invite_url and r.invite_url.startswith(f"{FRONTEND}/accept-invite?token=")
    raw = r.invite_url.split("token=", 1)[1]
    org = await _org(slug)
    assert org and org.status == "active" and org.schema_name == f"tenant_{slug}"
    assert await _schema_exists(org.schema_name)
    async with db.get_session_factory()() as s:
        inv = await s.scalar(select(Invitation).where(Invitation.org_id == org.id))
        assert inv is not None and inv.role_key == "owner" and inv.accepted_at is None
        # Only the hash is stored, never the raw token.
        assert inv.token_hash == hash_token(raw) and raw not in inv.token_hash
        assert await s.scalar(select(User).where(User.email == f"owner@{slug}.test")) is None
    created = [x for x in _audit_lines(audit_log) if x["action"] == "org.created"]
    assert created and created[-1]["org"] == slug and created[-1]["actor"] == "cli:pytest"


@pytest.mark.integration
async def test_provision_with_password(migrated: str, new_slug: Callable[[str], str]) -> None:
    slug = new_slug("pwd")
    r = await _provision(slug, password=STRONG)
    assert (r.owner_status, r.invite_url) == ("created", None)
    async with db.get_session_factory()() as s:
        user = await s.scalar(select(User).where(User.email == f"owner@{slug}.test"))
        assert user and user.is_active and user.is_verified and not user.is_platform_admin
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(STRONG, user.password_hash)
        assert not verify_password("wrong-password-1", user.password_hash)
        m = await s.scalar(select(OrgMembership).where(OrgMembership.user_id == user.id))
        assert m and m.status == "active"
    async with tenant_session(r.schema_name) as ts:
        role = await ts.scalar(
            select(Role.key)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
        assert role == "owner"


@pytest.mark.integration
async def test_existing_user_becomes_owner_password_ignored(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    # B04 D1: the existing account must not belong to an org yet.
    email = f"loner_{uuid.uuid4().hex[:6]}@x.test"
    async with db.get_session_factory()() as s, s.begin():
        s.add(User(email=email, password_hash=hash_password(STRONG)))
    r = await _provision(new_slug("first"), email=email, password="another-pass-99")
    assert r.owner_status == "existing"
    assert any("password ignored" in n for n in r.notes)
    async with db.get_session_factory()() as s:
        user = await s.scalar(select(User).where(User.email == email))
        assert user and verify_password(STRONG, user.password_hash)  # unchanged


@pytest.mark.integration
async def test_owner_of_another_org_is_refused(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    """B04 D1/D2: one organization per user, also for owners."""
    email = f"shared_{uuid.uuid4().hex[:6]}@x.test"
    await _provision(new_slug("first"), email=email, password=STRONG)
    second = new_slug("second")
    with pytest.raises(Conflict, match="already a member of another organization"):
        await _provision(second, email=email, password=STRONG)
    org = await _org(second)
    assert org is not None and org.status == "failed"
    assert not await _schema_exists(org.schema_name)  # half tenant cleaned up


@pytest.mark.integration
async def test_weak_password_rejected(migrated: str, new_slug: Callable[[str], str]) -> None:
    slug = new_slug("weak")
    with pytest.raises(BadRequest, match="at least 12"):
        await _provision(slug, password="short1")
    assert await _org(slug) is None  # rejected before anything was written


# ---------------------------------- T8 ------------------------------------- #
@pytest.mark.integration
async def test_rerun_is_noop(migrated: str, new_slug: Callable[[str], str]) -> None:
    slug = new_slug("rerun")
    await _provision(slug)
    r2 = await _provision(slug)
    assert (r2.outcome, r2.owner_status) == ("already_active", "skipped")


@pytest.mark.integration
async def test_duplicate_slug_different_name_conflicts(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    slug = new_slug("dup")
    await _provision(slug, name="Original")
    with pytest.raises(Conflict, match="already belongs"):
        await _provision(slug, name="Impostor")


@pytest.mark.integration
async def test_failure_drops_schema_created_by_this_run(
    migrated: str,
    new_slug: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
    audit_log: Path,
) -> None:
    slug = new_slug("fail")

    async def boom(_schema: str) -> None:
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(provisioning.migrations, "upgrade_tenant", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        await _provision(slug)
    org = await _org(slug)
    assert org and org.status == "failed"
    assert not await _schema_exists(f"tenant_{slug}")  # cleaned up
    assert any(
        x["action"] == "org.provision_failed" and x["result"] == "error"
        for x in _audit_lines(audit_log)
    )

    # Resume: same command again, failure gone.
    monkeypatch.undo()  # restore the real upgrade_tenant
    r = await _provision(slug)
    assert r.outcome == "resumed"
    org = await _org(slug)
    assert org and org.status == "active"


@pytest.mark.integration
async def test_failure_keeps_preexisting_schema(
    migrated: str, new_slug: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = new_slug("keep")
    async with db.get_engine().begin() as c:
        await c.execute(text(f'CREATE SCHEMA "tenant_{slug}"'))  # made by a human / earlier run

    async def boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("simulated seed failure")

    monkeypatch.setattr(provisioning, "seed_tenant", boom)
    with pytest.raises(RuntimeError):
        await _provision(slug)
    assert await _schema_exists(f"tenant_{slug}")  # NOT dropped: this run did not create it


# ---------------------------------- T9 ------------------------------------- #
async def _user_with_membership(org_slug: str | None, *, admin: bool = False) -> uuid.UUID:
    async with db.get_session_factory()() as s, s.begin():
        u = User(
            email=f"u_{uuid.uuid4().hex[:8]}@x.test", password_hash="x", is_platform_admin=admin
        )
        s.add(u)
        await s.flush()
        if org_slug:
            org = await s.scalar(select(Organization).where(Organization.slug == org_slug))
            assert org
            s.add(OrgMembership(user_id=u.id, org_id=org.id))
        return u.id


@pytest.mark.integration
async def test_resolve_tenant_rules(
    migrated: str, new_slug: Callable[[str], str], audit_log: Path
) -> None:
    acme, beta = new_slug("acme"), new_slug("beta")
    await _provision(acme)
    await _provision(beta)
    member = await _user_with_membership(acme)
    admin = await _user_with_membership(None, admin=True)

    async with db.get_session_factory()() as s:
        ctx = await resolve_tenant(s, acme.upper(), user_id=member)  # header case-insensitive
        assert ctx == TenantContext(ctx.org_id, acme, acme.title(), f"tenant_{acme}")

        messages = set()
        for slug in (beta, "nosuchorg", "acme; DROP SCHEMA public", 'x" or "1"="1', ""):
            with pytest.raises(NotFound) as ei:
                await resolve_tenant(s, slug, user_id=member)
            messages.add(ei.value.message)
        assert messages == {"Organization not found"}  # identical for every failure (D5)

        # Platform_Admin: allowed without membership, and audited.
        ctx2 = await resolve_tenant(s, beta, user_id=admin, is_platform_admin=True)
        assert ctx2.slug == beta
    assert any(
        x["action"] == "tenancy.platform_admin_access" and x["org"] == beta
        for x in _audit_lines(audit_log)
    )
    assert await _schema_exists("tenant_" + acme)  # injection attempts executed nothing


@pytest.mark.integration
async def test_suspended_tenant_is_not_found(migrated: str, new_slug: Callable[[str], str]) -> None:
    slug = new_slug("susp")
    await _provision(slug)
    member = await _user_with_membership(slug)
    async with db.get_session_factory()() as s, s.begin():
        await s.execute(
            text("UPDATE organizations SET status='suspended' WHERE slug=:s"), {"s": slug}
        )
    async with db.get_session_factory()() as s:
        with pytest.raises(NotFound, match="Organization not found"):
            await resolve_tenant(s, slug, user_id=member)


@pytest.mark.integration
async def test_inactive_membership_is_not_found(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    slug = new_slug("inact")
    await _provision(slug)
    member = await _user_with_membership(slug)
    async with db.get_session_factory()() as s, s.begin():
        await s.execute(
            text("UPDATE org_memberships SET status='inactive' WHERE user_id=:u"), {"u": member}
        )
    async with db.get_session_factory()() as s:
        with pytest.raises(NotFound):
            await resolve_tenant(s, slug, user_id=member)


# ---------------------------------- T10 ------------------------------------ #
@pytest.mark.integration
async def test_tenant_sessions_are_isolated(migrated: str, new_slug: Callable[[str], str]) -> None:
    acme, beta = new_slug("isoa"), new_slug("isob")
    for slug in (acme, beta):
        await _provision(slug)
        async with tenant_session(f"tenant_{slug}") as s:
            s.add(Setting(key="marker", value=slug))

    async def read_marker(slug: str) -> tuple[str, object, list[object]]:
        async with tenant_session(f"tenant_{slug}") as s:
            await s.execute(text("SELECT pg_sleep(0.02)"))  # force overlap on pooled conns
            marker = await s.scalar(select(Setting.value).where(Setting.key == "marker"))
            all_markers = (
                await s.scalars(select(Setting.value).where(Setting.key == "marker"))
            ).all()
            return slug, marker, list(all_markers)

    results = await asyncio.gather(*(read_marker(acme if i % 2 else beta) for i in range(50)))
    for slug, marker, all_markers in results:
        assert marker == slug and all_markers == [slug]

    # Pooled connections come back clean.
    async with db.get_engine().connect() as c:
        assert await c.scalar(text("SHOW search_path")) == '"$user", public'


@pytest.mark.integration
async def test_tenant_session_refuses_bad_schema(migrated: str) -> None:
    for bad in ("public", "tenant_x; drop", "pg_catalog", "tenant_"):
        with pytest.raises(ValueError, match="invalid schema"):
            async with tenant_session(bad):
                pass


@pytest.mark.integration
async def test_tenant_session_rolls_back_on_error(
    migrated: str, new_slug: Callable[[str], str]
) -> None:
    slug = new_slug("rollb")
    await _provision(slug)
    with pytest.raises(RuntimeError):
        async with tenant_session(f"tenant_{slug}") as s:
            s.add(Setting(key="should_vanish", value=1))
            await s.flush()
            raise RuntimeError("handler failed")
    async with tenant_session(f"tenant_{slug}") as s:
        assert await s.scalar(select(Setting).where(Setting.key == "should_vanish")) is None
