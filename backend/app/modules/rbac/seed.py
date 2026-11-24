"""Default roles, grants and settings for a tenant (design B02 §3.7).

Seeds are the source of truth for DEFAULTS (system_design §4). Seeding is an
idempotent upsert that never removes or overwrites anything, and default
grants are applied only to roles created in the same run, so grants edited in
DBeaver on a live tenant survive a re-run (data_model §6).
"""

from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import TENANT_ROLE_KEYS, load_module_permissions
from app.models.tenant import Permission, Role, RolePermission, Setting

log = structlog.get_logger("app.rbac.seed")


@dataclass(frozen=True)
class RoleDef:
    key: str
    name: str
    priority: int  # lower wins for the landing page
    landing_path: str


# object_msterlist.md §B. platform_admin is a user flag, not a tenant role.
SYSTEM_ROLES: tuple[RoleDef, ...] = (
    RoleDef("owner", "Owner", 10, "/home/owner"),
    RoleDef("admin", "Admin", 20, "/home/admin"),
    RoleDef("manager", "Manager", 30, "/home/manager"),
    RoleDef("staff", "Staff", 40, "/home/staff"),
    RoleDef("user", "User", 50, "/home/user"),
)


# B06 D2: the default matrix is no longer written here. Each module declares
# `default_roles` on its PermissionDefs (system_design.md §4 lives in the
# modules' permissions.py files); this is the derived role -> keys view.
def default_grants() -> dict[str, frozenset[str]]:
    defs = load_module_permissions()
    return {r.key: frozenset(d.key for d in defs if r.key in d.default_roles) for r in SYSTEM_ROLES}


if {r.key for r in SYSTEM_ROLES} != set(TENANT_ROLE_KEYS):  # fail at import, not at runtime
    raise RuntimeError("SYSTEM_ROLES and core.permissions.TENANT_ROLE_KEYS disagree")

# Kept for readers and existing tests; computed once at import. Seeding calls
# default_grants() itself so modules registered later are included.
DEFAULT_GRANTS: dict[str, frozenset[str]] = default_grants()


def default_settings(org_name: str) -> dict[str, Any]:
    return {"app.display_name": org_name}


@dataclass
class SeedReport:
    roles_added: int = 0
    permissions_added: int = 0
    grants_added: int = 0
    settings_added: int = 0
    unknown_grant_keys: list[str] = field(default_factory=list)


async def sync_permissions(session: AsyncSession) -> int:
    """Upsert every registered permission key; grant defaults for NEW keys only.

    B06 D1: a key inserted by THIS run also gets its module's `default_roles`
    granted to the roles that exist. Keys that were already there are left
    alone, grants included, so a grant an operator removed is never restored.
    Returns the number of NEW keys. `session` must be a tenant_session.
    """
    defs = {d.key: d for d in load_module_permissions()}
    if not defs:
        return 0
    result = await session.execute(
        insert(Permission)
        .values(
            [
                {"key": d.key, "module": d.module, "description": d.description}
                for d in defs.values()
            ]
        )
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(Permission.key, Permission.id)
    )
    new_keys = {k: pid for k, pid in result.all()}
    granted = 0
    if new_keys:
        role_ids = {k: v for k, v in (await session.execute(select(Role.key, Role.id))).all()}
        rows = [
            {"role_id": role_ids[role], "permission_id": pid}
            for key, pid in sorted(new_keys.items())
            for role in sorted(defs[key].default_roles)
            if role in role_ids  # a tenant without that role simply gets no grant
        ]
        if rows:
            res = await session.execute(
                insert(RolePermission)
                .values(rows)
                .on_conflict_do_nothing()
                .returning(RolePermission.role_id)
            )
            granted = len(res.all())
    log.info(
        "rbac.permissions_synced",
        added=len(new_keys),
        grants_added=granted,
        total=len(defs),
        new_keys=sorted(new_keys),
    )
    return len(new_keys)


async def seed_tenant(session: AsyncSession, org_name: str) -> SeedReport:
    """Idempotently seed roles, permissions, default grants and settings."""
    report = SeedReport()

    res = await session.execute(
        insert(Role)
        .values(
            [
                {
                    "key": r.key,
                    "name": r.name,
                    "priority": r.priority,
                    "landing_path": r.landing_path,
                    "is_system": True,
                }
                for r in SYSTEM_ROLES
            ]
        )
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(Role.key)
    )
    new_roles = {row[0] for row in res.all()}
    report.roles_added = len(new_roles)

    report.permissions_added = await sync_permissions(session)

    role_ids = {k: v for k, v in (await session.execute(select(Role.key, Role.id))).all()}
    perm_ids = {
        k: v for k, v in (await session.execute(select(Permission.key, Permission.id))).all()
    }
    rows = []
    # Default grants only for roles created IN THIS RUN. Re-seeding an existing
    # tenant must not resurrect a grant an operator removed in DBeaver. This is
    # safe for resumed provisioning: seeding runs in one transaction, so a
    # failed run leaves no roles behind and the retry seeds everything.
    for role_key, perm_keys in default_grants().items():
        if role_key not in new_roles:
            continue
        for pk in sorted(perm_keys):
            if pk not in perm_ids:
                # A matrix entry without a registered key is a programming error
                # in this file; report it instead of silently skipping.
                report.unknown_grant_keys.append(pk)
                continue
            rows.append({"role_id": role_ids[role_key], "permission_id": perm_ids[pk]})
    if rows:
        res = await session.execute(
            insert(RolePermission)
            .values(rows)
            .on_conflict_do_nothing()
            .returning(RolePermission.role_id)
        )
        report.grants_added = len(res.all())

    res = await session.execute(
        insert(Setting)
        .values([{"key": k, "value": v} for k, v in default_settings(org_name).items()])
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(Setting.key)
    )
    report.settings_added = len(res.all())

    if report.unknown_grant_keys:
        log.error("rbac.seed_unknown_keys", keys=sorted(set(report.unknown_grant_keys)))
        raise RuntimeError(
            f"grant matrix references unregistered keys: {report.unknown_grant_keys}"
        )
    log.info(
        "rbac.seeded", **{k: v for k, v in report.__dict__.items() if k != "unknown_grant_keys"}
    )
    return report
