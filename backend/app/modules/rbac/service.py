"""RBAC reads and role assignment (design B04 §3.5, D6, D7).

Grants (role -> permission) are edited in SQL/DBeaver, not through the API
(system_design §4). The API only reads them and assigns roles to members.
"""

import uuid

import structlog
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.core.permissions import TenantAccess, invalidate_access
from app.models.tenant import Permission, Role, RolePermission, UserRole
from app.modules.rbac.schemas import PermissionOut, RoleOut
from app.modules.users.schemas import MemberOut
from app.modules.users.service import (
    OWNER_ROLE,
    active_owner_count,
    get_member_or_404,
    guard_target,
    member_out,
    rank_of,
    roles_of,
)

log = structlog.get_logger("app.rbac")


async def list_roles(ts: AsyncSession) -> list[RoleOut]:
    roles = (await ts.scalars(select(Role).order_by(Role.priority))).all()
    grants = (
        await ts.execute(
            select(RolePermission.role_id, Permission.key)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .order_by(Permission.key)
        )
    ).all()
    by_role: dict[uuid.UUID, list[str]] = {}
    for role_id, key in grants:
        by_role.setdefault(role_id, []).append(key)
    return [
        RoleOut(
            key=r.key,
            name=r.name,
            priority=r.priority,
            landing_path=r.landing_path,
            is_system=r.is_system,
            permissions=by_role.get(r.id, []),
        )
        for r in roles
    ]


async def list_permissions(ts: AsyncSession) -> list[PermissionOut]:
    rows = (await ts.scalars(select(Permission).order_by(Permission.key))).all()
    return [PermissionOut(key=p.key, module=p.module, description=p.description) for p in rows]


async def set_roles(
    ts: AsyncSession,
    redis: Redis | None,
    access: TenantAccess,
    user_id: uuid.UUID,
    role_keys: list[str],
) -> MemberOut:
    """Replace a member's roles (PUT semantics) under the D6/D7 rules."""
    wanted = list(dict.fromkeys(k.strip() for k in role_keys if k.strip()))  # dedupe, keep order
    if not wanted:
        raise ValidationFailed(
            "a member needs at least one role",
            fields=[{"loc": ["body", "role_keys"], "msg": "empty", "type": "too_short"}],
        )
    all_roles = {r.key: r for r in (await ts.scalars(select(Role))).all()}
    unknown = [k for k in wanted if k not in all_roles]
    if unknown:
        raise ValidationFailed(
            f"unknown role(s): {', '.join(unknown)}",
            fields=[{"loc": ["body", "role_keys"], "msg": "unknown role", "type": "unknown_role"}],
        )

    org_id = access.tenant.org_id
    user, membership = await get_member_or_404(ts, org_id, user_id)
    current = (await roles_of(ts, [user.id]))[user.id]
    guard_target(access, user.id, rank_of(current))

    old_keys = {r.key for r in current}
    new_keys = set(wanted)
    changed = old_keys ^ new_keys  # roles being granted or removed
    too_senior = sorted(k for k in changed if all_roles[k].priority < access.rank)
    if too_senior:
        raise PermissionDenied(f"You cannot assign or remove a role above your own: {too_senior}")

    if not changed:
        return member_out(user, membership, current)

    losing_owner = OWNER_ROLE in old_keys and OWNER_ROLE not in new_keys
    if losing_owner and membership.status == "active" and user.is_active:
        if await active_owner_count(ts, org_id) <= 1:
            raise Conflict("The last active owner cannot lose the owner role")

    remove_ids = [all_roles[k].id for k in old_keys - new_keys]
    if remove_ids:
        await ts.execute(
            delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id.in_(remove_ids))
        )
    for k in sorted(new_keys - old_keys):
        ts.add(UserRole(user_id=user.id, role_id=all_roles[k].id, assigned_by=access.user_id))
    await ts.commit()
    await invalidate_access(redis, org_id, user.id)

    ordered = sorted(new_keys, key=lambda k: all_roles[k].priority)
    audit.record(
        "roles.assign",
        entity="user",
        entity_id=str(user.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"roles": [sorted(old_keys, key=lambda k: all_roles[k].priority), ordered]},
        sensitive=True,
    )
    log.info("rbac.roles_assigned", user_id=str(user.id), roles=ordered)
    return member_out(user, membership, [all_roles[k] for k in ordered])
