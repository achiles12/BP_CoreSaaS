"""Permission registry and enforcement (design B02 §3.5, B04 §3.2; object S04).

Permissions are DATA (deliverables reusability rule 2): each module declares
its keys in `app/modules/<module>/permissions.py` by calling `register()`.
Provisioning and `sync-permissions` copy the registry into every tenant's
`permissions` table.

Enforcement (B04): tenant endpoints declare `Depends(require("files:write"))`.
The chain is current_verified_user -> X-Tenant -> resolve_tenant (membership
checked against the DB on EVERY request) -> role/permission set (Redis cache,
60 s) -> 403 when the key is missing.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import structlog
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import PermissionDenied
from app.core.security import CurrentUser, current_verified_user
from app.core.tenancy import TenantContext, read_tenant_header, resolve_tenant, tenant_session
from app.models.public import User
from app.models.tenant import Permission, Role, RolePermission, UserRole

log = structlog.get_logger("app.permissions")

PLATFORM_MANAGE = "platform:manage"
PLATFORM_ADMIN_RANK = 0  # above owner (10): B04 D6
PLATFORM_LANDING = "/platform"
NO_ROLE_RANK = 1000  # a member without roles ranks below everyone
CACHE_TTL_S = 60  # system_design §2 step 5
CACHE_PREFIX = "perm"

KEY_PATTERN = re.compile(r"^[a-z_]+:[a-z_]+$")

# The five tenant roles every tenant is seeded with (rbac/seed.py SYSTEM_ROLES).
# Declared here so a module's default_roles can be checked at import time.
TENANT_ROLE_KEYS: tuple[str, ...] = ("owner", "admin", "manager", "staff", "user")
ALL_ROLES: frozenset[str] = frozenset(TENANT_ROLE_KEYS)
# Common default_roles sets, named after who gets the key (system_design.md §4).
OWNER: frozenset[str] = frozenset({"owner"})
OWNER_ADMIN: frozenset[str] = frozenset({"owner", "admin"})
OWNER_ADMIN_MANAGER: frozenset[str] = frozenset({"owner", "admin", "manager"})
STAFF_UP: frozenset[str] = frozenset({"owner", "admin", "manager", "staff"})


@dataclass(frozen=True)
class PermissionDef:
    """A permission key declared by a module.

    default_roles (B06 D1): the roles that get this key in a NEW tenant, and in
    existing tenants when `sync-permissions` first adds the key. Grants are
    never re-applied later, so an operator's removal sticks.
    """

    key: str
    description: str
    default_roles: frozenset[str] = frozenset()

    @property
    def module(self) -> str:
        return self.key.split(":", 1)[0]


_registry: dict[str, PermissionDef] = {}


def register(defs: list[PermissionDef]) -> None:
    """Add a module's permissions. Duplicate or malformed keys fail at import."""
    for d in defs:
        if not KEY_PATTERN.fullmatch(d.key):
            raise ValueError(f"invalid permission key {d.key!r} (expected module:action)")
        unknown = set(d.default_roles) - ALL_ROLES
        if unknown:
            raise ValueError(f"permission {d.key!r}: unknown default roles {sorted(unknown)}")
        if d.key in _registry and _registry[d.key] != d:
            raise ValueError(f"permission {d.key!r} registered twice")
        _registry[d.key] = d


def load_module_permissions() -> list[PermissionDef]:
    """Import every registered module's permissions.py (idempotent); return all keys."""
    from app.modules import registry  # late import: modules import this file

    registry.load_permissions()
    return all_permissions()


def all_permissions() -> list[PermissionDef]:
    return sorted(_registry.values(), key=lambda d: d.key)


# --------------------------------------------------------------------------- #
# Role/permission set of one user in one tenant (B04 §3.2)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RoleSet:
    roles: tuple[str, ...]  # role keys, highest priority first
    permissions: frozenset[str]
    rank: int  # lowest priority value among roles (lower = more senior)
    landing_path: str | None


@dataclass(frozen=True)
class TenantAccess:
    """Everything a tenant endpoint needs to know about the caller."""

    user: User
    tenant: TenantContext
    roles: tuple[str, ...]
    permissions: frozenset[str]
    rank: int
    landing_path: str | None
    is_platform_admin: bool

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


def _cache_key(org_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"{CACHE_PREFIX}:{org_id}:{user_id}"


async def _query_role_set(ts: AsyncSession, user_id: uuid.UUID, platform_admin: bool) -> RoleSet:
    """Read roles + permissions from the tenant schema (ts = tenant_session)."""
    roles = (
        await ts.execute(
            select(Role.key, Role.priority, Role.landing_path)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.priority)
        )
    ).all()
    if platform_admin:
        # B04 D13: full access inside any tenant (entry is audited by resolve_tenant).
        perms = set((await ts.scalars(select(Permission.key))).all()) | {PLATFORM_MANAGE}
        return RoleSet(
            tuple(r[0] for r in roles), frozenset(perms), PLATFORM_ADMIN_RANK, PLATFORM_LANDING
        )
    perms = set(
        (
            await ts.scalars(
                select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(UserRole, UserRole.role_id == RolePermission.role_id)
                .where(UserRole.user_id == user_id)
                .distinct()
            )
        ).all()
    )
    if not roles:
        return RoleSet((), frozenset(perms), NO_ROLE_RANK, None)
    # Landing page = the highest-priority (lowest number) role (system_design §4).
    return RoleSet(tuple(r[0] for r in roles), frozenset(perms), roles[0][1], roles[0][2])


async def load_access(redis: Redis | None, user: User, tenant: TenantContext) -> RoleSet:
    """Role set with a 60 s Redis cache (D12). Redis problems -> read the DB."""
    key = _cache_key(tenant.org_id, user.id)
    if redis is not None:
        try:
            raw = await redis.get(key)
            if raw:
                d = json.loads(raw)
                return RoleSet(
                    tuple(d["roles"]), frozenset(d["permissions"]), d["rank"], d["landing_path"]
                )
        except Exception as exc:  # cache is an optimisation: never fail the request
            log.warning("permissions.cache_read_failed", error=str(exc))

    async with tenant_session(tenant) as ts:
        rs = await _query_role_set(ts, user.id, user.is_platform_admin)

    if redis is not None:
        try:
            payload = {
                "roles": list(rs.roles),
                "permissions": sorted(rs.permissions),
                "rank": rs.rank,
                "landing_path": rs.landing_path,
            }
            await redis.set(key, json.dumps(payload), ex=CACHE_TTL_S)
        except Exception as exc:
            log.warning("permissions.cache_write_failed", error=str(exc))
    return rs


async def invalidate_access(redis: Redis | None, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Drop the cached role set after a role change / (de)activation. Never raises."""
    if redis is None:
        return
    try:
        await redis.delete(_cache_key(org_id, user_id))
        log.info("permissions.cache_invalidated", org_id=str(org_id), user_id=str(user_id))
    except Exception as exc:
        # Worst case the old set lives for CACHE_TTL_S; membership status is
        # still checked against the DB on every request.
        log.warning("permissions.cache_invalidate_failed", error=str(exc))


def _redis(request: Request) -> Redis | None:
    return getattr(request.app.state, "redis", None)


async def tenant_access(
    request: Request,
    caller: Annotated[CurrentUser, Depends(current_verified_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TenantAccess:
    """Caller + tenant + role set for tenant-scoped routes (B04 §4)."""
    slug = read_tenant_header(request)  # 400 when missing
    tenant = await resolve_tenant(
        session, slug, user_id=caller.id, is_platform_admin=caller.user.is_platform_admin
    )
    # Give the public session's connection back to the pool BEFORE any tenant
    # session is opened (load_access below, tenant_db in the route). Otherwise
    # every tenant request holds two pooled connections at once, and more
    # concurrent requests than the pool size (5 + 10 overflow) deadlock until
    # the pool timeout (found by the B12 50-parallel isolation test). The
    # session only read so far; expire_on_commit=False keeps the loaded user.
    await session.commit()
    rs = await load_access(_redis(request), caller.user, tenant)
    structlog.contextvars.bind_contextvars(org=tenant.slug)
    return TenantAccess(
        user=caller.user,
        tenant=tenant,
        roles=rs.roles,
        permissions=rs.permissions,
        rank=rs.rank,
        landing_path=rs.landing_path,
        is_platform_admin=caller.user.is_platform_admin,
    )


def require(key: str) -> Callable[..., Awaitable[TenantAccess]]:
    """Dependency factory: `Depends(require("users:invite"))` -> TenantAccess or 403.

    The key is validated against the registry when the route is DEFINED, so a
    typo fails at startup instead of silently denying everyone.
    """
    load_module_permissions()
    if key not in _registry:
        raise ValueError(f"require({key!r}): permission key is not registered")

    async def _check(access: Annotated[TenantAccess, Depends(tenant_access)]) -> TenantAccess:
        if key not in access.permissions:
            log.info("permissions.denied", key=key, roles=list(access.roles))
            raise PermissionDenied(f"Missing permission {key}")
        return access

    _check.__name__ = f"require_{key.replace(':', '_')}"
    # Read by the generated permission matrix (B12 D3): which key this route needs.
    _check.required_permission = key  # type: ignore[attr-defined]
    return _check


async def tenant_db(
    access: Annotated[TenantAccess, Depends(tenant_access)],
) -> AsyncIterator[AsyncSession]:
    """Tenant-bound session for the request. It can also write public tables
    (they carry an explicit schema), so cross-schema changes stay atomic."""
    async with tenant_session(access.tenant) as ts:
        yield ts


async def require_platform_admin(
    caller: Annotated[CurrentUser, Depends(current_verified_user)],
) -> CurrentUser:
    if not caller.user.is_platform_admin:
        log.info("permissions.denied", key=PLATFORM_MANAGE)
        raise PermissionDenied(f"Missing permission {PLATFORM_MANAGE}")
    return caller
