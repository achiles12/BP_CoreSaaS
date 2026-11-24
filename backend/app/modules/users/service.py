"""Users, /me and invitations: business rules (design B04 §3.4, D1–D15).

Session conventions:
- Tenant endpoints get a tenant_session (`ts`). Public tables carry an explicit
  `public` schema, so the same session/transaction can change users,
  memberships and invitations together with tenant rows (user_roles): one
  commit, all or nothing.
- Services commit, THEN queue email / drop caches / write audit lines, so
  side effects only describe committed state.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import audit, db, mail
from app.core.errors import BadRequest, Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import FilterField, ListQuery, ListSpec, paginate
from app.core.permissions import (
    NO_ROLE_RANK,
    PLATFORM_LANDING,
    PLATFORM_MANAGE,
    TenantAccess,
    invalidate_access,
    load_access,
)
from app.core.security import (
    WeakPasswordError,
    hash_password,
    hash_token,
    new_token,
    validate_password_strength,
    verify_password,
)
from app.core.tenancy import TenantContext, resolve_tenant, tenant_session
from app.models.public import Invitation, Organization, OrgMembership, User
from app.models.tenant import Role, UserRole
from app.modules.auth.schemas import UserOut
from app.modules.auth.service import revoke_user_sessions
from app.modules.users.schemas import InvitationOut, MemberOut, MeOut, OrgRef

log = structlog.get_logger("app.users")

INVITE_TTL = timedelta(days=7)  # backend_processes.md §5
OWNER_ROLE = "owner"
INVALID_INVITATION = "Invalid or expired invitation"


def _now() -> datetime:
    return datetime.now(UTC)


def _tenant_of(org: Organization) -> TenantContext:
    return TenantContext(org_id=org.id, slug=org.slug, name=org.name, schema_name=org.schema_name)


def _escape_like(q: str) -> str:
    """Literal substring search: user input must not act as LIKE wildcards."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --------------------------------------------------------------------------- #
# /me (D4, D13, D15)
# --------------------------------------------------------------------------- #
async def get_me(
    s: AsyncSession, redis: Redis | None, user: User, tenant_slug: str | None
) -> MeOut:
    tenant: TenantContext | None = None
    if tenant_slug:
        # Same checks as tenant endpoints: unknown / not-a-member -> 404 (B02 D5).
        tenant = await resolve_tenant(
            s, tenant_slug, user_id=user.id, is_platform_admin=user.is_platform_admin
        )
    else:
        org = await s.scalar(
            select(Organization)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(
                OrgMembership.user_id == user.id,
                OrgMembership.status == "active",
                Organization.status == "active",
            )
        )
        tenant = _tenant_of(org) if org else None

    base = {
        "user": UserOut.model_validate(user),
        "is_platform_admin": user.is_platform_admin,
        "is_verified": user.is_verified,
    }
    if tenant is None:
        if user.is_platform_admin:
            return MeOut(
                **base,
                org=None,
                roles=[],
                permissions=[PLATFORM_MANAGE],
                landing_path=PLATFORM_LANDING,
            )
        log.info("me.no_organization", user_id=str(user.id))
        return MeOut(**base, org=None, roles=[], permissions=[], landing_path=None)

    rs = await load_access(redis, user, tenant)
    return MeOut(
        **base,
        org=OrgRef(id=tenant.org_id, slug=tenant.slug, name=tenant.name),
        roles=list(rs.roles),
        permissions=sorted(rs.permissions),
        landing_path=rs.landing_path,
    )


async def update_me(s: AsyncSession, user: User, full_name: str) -> User:
    old = user.full_name
    user.full_name = full_name
    await s.commit()
    audit.record(
        "users.update_self",
        entity="user",
        entity_id=str(user.id),
        actor=str(user.id),
        diff={"full_name": [old, full_name]},
    )
    return user


# --------------------------------------------------------------------------- #
# helpers shared with rbac
# --------------------------------------------------------------------------- #
async def get_member_or_404(
    ts: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[User, OrgMembership]:
    row = (
        await ts.execute(
            select(User, OrgMembership)
            .join(OrgMembership, OrgMembership.user_id == User.id)
            .where(User.id == user_id, OrgMembership.org_id == org_id)
        )
    ).first()
    if row is None:
        raise NotFound("User not found")
    return row[0], row[1]


async def roles_of(ts: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Role]]:
    """Role rows per user, highest priority first."""
    out: dict[uuid.UUID, list[Role]] = {u: [] for u in user_ids}
    if not user_ids:
        return out
    rows = (
        await ts.execute(
            select(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
            .order_by(Role.priority)
        )
    ).all()
    for uid, role in rows:
        out[uid].append(role)
    return out


def rank_of(roles: list[Role]) -> int:
    return min((r.priority for r in roles), default=NO_ROLE_RANK)


def guard_target(access: TenantAccess, target_id: uuid.UUID, target_rank: int) -> None:
    """D6: only members ranked at or below the caller can be managed (self is fine)."""
    if target_id != access.user_id and target_rank < access.rank:
        log.info("users.target_outranks_caller", target_rank=target_rank, rank=access.rank)
        raise PermissionDenied("You cannot manage a member with a more senior role")


async def active_owner_count(ts: AsyncSession, org_id: uuid.UUID) -> int:
    """Owners whose membership AND account are active (D7)."""
    return int(
        await ts.scalar(
            select(func.count(func.distinct(UserRole.user_id)))
            .join(Role, Role.id == UserRole.role_id)
            .join(OrgMembership, OrgMembership.user_id == UserRole.user_id)
            .join(User, User.id == UserRole.user_id)
            .where(
                Role.key == OWNER_ROLE,
                OrgMembership.org_id == org_id,
                OrgMembership.status == "active",
                User.is_active.is_(True),
            )
        )
        or 0
    )


def member_out(user: User, membership: OrgMembership, roles: list[Role]) -> MemberOut:
    return MemberOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=membership.status,
        is_verified=user.is_verified,
        roles=[r.key for r in roles],
        joined_at=membership.created_at,
    )


# --------------------------------------------------------------------------- #
# members
# --------------------------------------------------------------------------- #
# B06 D9: what GET /users may sort and filter by.
USERS_LIST = ListSpec(
    sort={"email": User.email, "full_name": User.full_name, "created_at": User.created_at},
    default_sort="email",
    filters={
        "status": FilterField(OrgMembership.status, "enum", choices=("active", "inactive")),
    },
)


def members_statement(
    org_id: uuid.UUID, q: str | None, status: str | None, lq: ListQuery
) -> Select:
    """The ONE query behind GET /users and the users export (B07 D4)."""
    stmt: Select = lq.apply(
        select(User, OrgMembership)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .where(OrgMembership.org_id == org_id)
    )
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(User.email.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\"))
        )
    if status:
        stmt = stmt.where(OrgMembership.status == status)
    return stmt


async def list_members(
    ts: AsyncSession, org_id: uuid.UUID, q: str | None, status: str | None, lq: ListQuery
) -> tuple[list[MemberOut], int]:
    rows, total = await paginate(ts, members_statement(org_id, q, status, lq), lq.page)
    by_user = await roles_of(ts, [r[0].id for r in rows])
    return [member_out(u, m, by_user[u.id]) for u, m in rows], total


async def get_member(ts: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> MemberOut:
    user, membership = await get_member_or_404(ts, org_id, user_id)
    return member_out(user, membership, (await roles_of(ts, [user.id]))[user.id])


async def update_member(
    ts: AsyncSession, access: TenantAccess, user_id: uuid.UUID, full_name: str
) -> MemberOut:
    user, membership = await get_member_or_404(ts, access.tenant.org_id, user_id)
    roles = (await roles_of(ts, [user.id]))[user.id]
    guard_target(access, user.id, rank_of(roles))
    old = user.full_name
    user.full_name = full_name
    await ts.commit()
    audit.record(
        "users.update",
        entity="user",
        entity_id=str(user.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"full_name": [old, full_name]},
    )
    return member_out(user, membership, roles)


async def set_member_active(
    ts: AsyncSession, redis: Redis | None, access: TenantAccess, user_id: uuid.UUID, active: bool
) -> MemberOut:
    """D5 + D7: (de)activate membership AND account; deactivation ends sessions."""
    org_id = access.tenant.org_id
    user, membership = await get_member_or_404(ts, org_id, user_id)
    roles = (await roles_of(ts, [user.id]))[user.id]
    if user.id == access.user_id:
        raise Conflict("You cannot change your own status")
    guard_target(access, user.id, rank_of(roles))

    currently_active = membership.status == "active" and user.is_active
    if currently_active == active:
        return member_out(user, membership, roles)  # idempotent: nothing to do
    if not active and any(r.key == OWNER_ROLE for r in roles):
        if await active_owner_count(ts, org_id) <= 1:
            raise Conflict("The last active owner cannot be deactivated")

    membership.status = "active" if active else "inactive"
    user.is_active = active
    revoked = 0 if active else await revoke_user_sessions(ts, user.id)
    await ts.commit()
    await invalidate_access(redis, org_id, user.id)
    audit.record(
        "users.activate" if active else "users.deactivate",
        entity="user",
        entity_id=str(user.id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={
            "status": ["inactive" if active else "active", membership.status],
            "revoked_tokens": revoked,
        },
        sensitive=True,
    )
    log.info("users.status_changed", user_id=str(user.id), active=active, revoked=revoked)
    return member_out(user, membership, roles)


# --------------------------------------------------------------------------- #
# invitations
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CreatedInvitation:
    invitation: Invitation
    link: str
    reissued: bool
    job_id: str | None


async def create_invitation(
    ts: AsyncSession,
    redis: ArqRedis | None,
    *,
    tenant: TenantContext,
    email: str,
    role_key: str,
    inviter: User | None,
    inviter_rank: int,
    actor: str,
    frontend_url: str,
) -> CreatedInvitation:
    """Create or re-issue an invitation and queue the invite email (D2, D6, D11).

    Shared by POST /users/invite and `cli invite-user` (inviter=None).
    `ts` must be a tenant_session of `tenant`. Commits.
    """
    role = await ts.scalar(select(Role).where(Role.key == role_key))
    if role is None:
        raise ValidationFailed(
            f"unknown role {role_key!r}",
            fields=[{"loc": ["body", "role_key"], "msg": "unknown role", "type": "unknown_role"}],
        )
    if role.priority < inviter_rank:
        raise PermissionDenied("You cannot invite someone to a role above your own")

    existing = await ts.scalar(select(User).where(User.email == email))
    if existing is not None:
        if existing.is_platform_admin:
            raise Conflict("This email belongs to a platform administrator")
        if await ts.scalar(select(OrgMembership.id).where(OrgMembership.user_id == existing.id)):
            raise Conflict("This email is already a member of an organization")

    raw, digest = new_token()
    expires = _now() + INVITE_TTL
    pending = await ts.scalar(
        select(Invitation).where(
            Invitation.org_id == tenant.org_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
        )
    )
    reissued = pending is not None
    if pending is not None:
        # Only hashes are stored: re-issuing rotates the token (old link dies).
        pending.token_hash, pending.expires_at, pending.role_key = digest, expires, role_key
        pending.invited_by = inviter.id if inviter else None
        inv = pending
    else:
        inv = Invitation(
            org_id=tenant.org_id,
            email=email,
            role_key=role_key,
            token_hash=digest,
            invited_by=inviter.id if inviter else None,
            expires_at=expires,
        )
        ts.add(inv)
    await ts.flush()
    await ts.commit()

    link = f"{frontend_url.rstrip('/')}/accept-invite?token={raw}"
    job_id = None
    if redis is not None:
        job_id = await mail.queue_email(
            redis,
            "invite_user",
            email,
            {
                "link": link,
                "org_name": tenant.name,
                "role_key": role.name,
                "inviter_name": (inviter.full_name or inviter.email) if inviter else None,
            },
            org_slug=tenant.slug,
        )
    audit.record(
        "users.invite",
        entity="invitation",
        entity_id=str(inv.id),
        org=tenant.slug,
        actor=actor,
        diff={
            "email": email,
            "role_key": role_key,
            "reissued": reissued,
            "email_queued": job_id is not None,
        },
    )
    log.info("users.invited", invitation_id=str(inv.id), reissued=reissued, queued=bool(job_id))
    return CreatedInvitation(inv, link, reissued, job_id)


def invitation_out(inv: Invitation, inviter_email: str | None) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role_key=inv.role_key,
        invited_by=inviter_email,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
        expired=inv.expires_at <= _now(),
    )


async def list_invitations(ts: AsyncSession, org_id: uuid.UUID) -> list[InvitationOut]:
    inviter = aliased(User)
    rows = (
        await ts.execute(
            select(Invitation, inviter.email)
            .outerjoin(inviter, inviter.id == Invitation.invited_by)
            .where(Invitation.org_id == org_id, Invitation.accepted_at.is_(None))
            .order_by(Invitation.created_at.desc())
        )
    ).all()
    return [invitation_out(inv, email) for inv, email in rows]


async def revoke_invitation(
    ts: AsyncSession, access: TenantAccess, invitation_id: uuid.UUID
) -> None:
    inv = await ts.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.org_id == access.tenant.org_id,
            Invitation.accepted_at.is_(None),
        )
    )
    if inv is None:
        raise NotFound("Invitation not found")
    role = await ts.scalar(select(Role).where(Role.key == inv.role_key))
    if role is not None and role.priority < access.rank:
        raise PermissionDenied("You cannot revoke an invitation to a role above your own")
    email = inv.email
    await ts.execute(delete(Invitation).where(Invitation.id == inv.id))
    await ts.commit()
    audit.record(
        "users.invitation_revoked",
        entity="invitation",
        entity_id=str(invitation_id),
        org=access.tenant.slug,
        actor=str(access.user_id),
        diff={"email": email, "role_key": inv.role_key},
    )


async def _valid_invitation(
    s: AsyncSession, token: str, *, lock: bool = False
) -> tuple[Invitation, Organization]:
    stmt = (
        select(Invitation, Organization)
        .join(Organization, Organization.id == Invitation.org_id)
        .where(
            Invitation.token_hash == hash_token(token),
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > _now(),
            Organization.status == "active",
        )
    )
    if lock:
        stmt = stmt.with_for_update(of=Invitation)  # serialise concurrent accepts
    row = (await s.execute(stmt)).first()
    if row is None:
        log.info("users.invitation_invalid")
        raise BadRequest(INVALID_INVITATION)
    return row[0], row[1]


async def invitation_info(s: AsyncSession, token: str) -> tuple[Invitation, Organization, bool]:
    """D9: (invitation, org, existing_account) for the accept page."""
    inv, org = await _valid_invitation(s, token)
    exists = await s.scalar(select(User.id).where(User.email == inv.email)) is not None
    return inv, org, exists


async def accept_invitation(token: str, password: str, full_name: str | None) -> User:
    """D8: create or attach the account, membership and role in ONE transaction."""
    async with db.get_session_factory()() as s:
        _, org = await _valid_invitation(s, token)
        schema = org.schema_name  # from the DB row, never from user input

    async with tenant_session(schema) as ts:
        inv, org = await _valid_invitation(ts, token, lock=True)
        role = await ts.scalar(select(Role).where(Role.key == inv.role_key))
        if role is None:
            raise Conflict("The invited role no longer exists; ask for a new invitation")

        user = await ts.scalar(select(User).where(User.email == inv.email))
        new_account = user is None
        if user is None:
            if not full_name:
                raise ValidationFailed(
                    "full name is required",
                    fields=[{"loc": ["body", "full_name"], "msg": "required", "type": "missing"}],
                )
            try:
                validate_password_strength(password)
            except WeakPasswordError as exc:
                raise ValidationFailed(
                    str(exc),
                    fields=[
                        {"loc": ["body", "password"], "msg": str(exc), "type": "weak_password"}
                    ],
                ) from exc
            user = User(
                email=inv.email,
                password_hash=hash_password(password),
                full_name=full_name,
                is_active=True,
                is_verified=True,  # the invite link proved the address (B03 D3)
            )
            ts.add(user)
            await ts.flush()
        else:
            if user.is_platform_admin:
                raise Conflict("This email belongs to a platform administrator")
            if await ts.scalar(select(OrgMembership.id).where(OrgMembership.user_id == user.id)):
                raise Conflict("This account is already a member of an organization")
            if not user.is_active:
                raise Conflict("This account is deactivated")
            # Never let an invite link set a password on an existing account.
            if not verify_password(password, user.password_hash):
                raise BadRequest("Current password is incorrect")
            user.is_verified = True

        ts.add(OrgMembership(user_id=user.id, org_id=org.id, status="active"))
        ts.add(UserRole(user_id=user.id, role_id=role.id, assigned_by=inv.invited_by))
        inv.accepted_at = _now()
        try:
            await ts.commit()
        except IntegrityError as exc:
            # Lost a race (same user accepting two invites at once): D1 unique.
            await ts.rollback()
            log.info("users.accept_conflict", error=str(exc.orig)[:200])
            raise Conflict("This account is already a member of an organization") from exc

    audit.record(
        "auth.invite_accepted",
        entity="invitation",
        entity_id=str(inv.id),
        org=org.slug,
        actor=str(user.id),
        diff={"email": inv.email, "role_key": inv.role_key, "new_account": new_account},
        sensitive=True,
    )
    log.info("users.invite_accepted", user_id=str(user.id), org=org.slug, new_account=new_account)
    return user
