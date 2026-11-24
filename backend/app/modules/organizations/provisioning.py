"""Tenant provisioning (design B02 §3.9, backend_processes.md §2).

Every step is idempotent and committed on its own, so re-running the same
command after a failure RESUMES where it stopped:

  1 validate input          4 tenant migrations     7 status active + audit
  2 organizations row       5 seed roles/grants
  3 CREATE SCHEMA           6 owner (existing / created / invited)

On failure: status -> 'failed', the schema is dropped ONLY if this run created
it (never destroy a schema an earlier run, or a human, created), an audit line
is written, and the exception propagates (CLI exits non-zero).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.core import audit, db, migrations
from app.core.errors import BadRequest, Conflict
from app.core.security import (
    WeakPasswordError,
    hash_password,
    new_token,
    validate_password_strength,
)
from app.core.tenancy import schema_for, tenant_session, validate_slug
from app.models.public import Invitation, Organization, OrgMembership, User
from app.models.tenant import Role, UserRole
from app.modules.rbac.seed import SeedReport, seed_tenant

log = structlog.get_logger("app.provisioning")

INVITE_TTL = timedelta(days=7)  # backend_processes.md §5
OWNER_ROLE = "owner"

Outcome = Literal["created", "resumed", "already_active"]
OwnerStatus = Literal["existing", "created", "invited", "skipped"]


@dataclass
class ProvisionResult:
    org_id: uuid.UUID
    slug: str
    schema_name: str
    outcome: Outcome
    owner_status: OwnerStatus
    invite_url: str | None = None
    seed: SeedReport = field(default_factory=SeedReport)
    notes: list[str] = field(default_factory=list)


def _validate_inputs(slug: str, name: str, owner_email: str, owner_password: str | None) -> str:
    slug = validate_slug(slug)
    if not name.strip():
        raise BadRequest("name must not be empty")
    # Deliberately simple: real validation (deliverability) is the invite flow's job.
    if "@" not in owner_email or owner_email.startswith("@") or owner_email.endswith("@"):
        raise BadRequest(f"invalid owner email {owner_email!r}")
    if owner_password is not None:
        try:
            validate_password_strength(owner_password)
        except WeakPasswordError as exc:
            raise BadRequest(str(exc)) from exc
    return slug


async def _schema_exists(schema: str) -> bool:
    async with db.get_engine().connect() as conn:
        return bool(
            await conn.scalar(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": schema},
            )
        )


async def _set_status(org_id: uuid.UUID, status: str) -> None:
    async with db.get_session_factory()() as s, s.begin():
        await s.execute(update(Organization).where(Organization.id == org_id).values(status=status))


async def _ensure_owner(
    org: Organization, email: str, password: str | None, frontend_url: str
) -> tuple[OwnerStatus, str | None, list[str]]:
    """Step 6. Returns (status, invite_url, notes)."""
    notes: list[str] = []
    async with db.get_session_factory()() as s, s.begin():
        user = await s.scalar(select(User).where(User.email == email))

        if user is None and password is None:
            # Default path (design D1): invitation, link printed by the CLI.
            raw, token_hash = new_token()
            expires = datetime.now(UTC) + INVITE_TTL
            pending = await s.scalar(
                select(Invitation).where(
                    Invitation.org_id == org.id,
                    Invitation.email == email,
                    Invitation.accepted_at.is_(None),
                )
            )
            if pending is not None:
                # Only the hash is stored, so an old link cannot be re-printed:
                # rotate the token (old link stops working) and extend expiry.
                pending.token_hash, pending.expires_at, pending.role_key = (
                    token_hash,
                    expires,
                    OWNER_ROLE,
                )
                notes.append("existing pending invitation re-issued (previous link invalid)")
            else:
                s.add(
                    Invitation(
                        org_id=org.id,
                        email=email,
                        role_key=OWNER_ROLE,
                        token_hash=token_hash,
                        expires_at=expires,
                    )
                )
            return "invited", f"{frontend_url.rstrip('/')}/accept-invite?token={raw}", notes

        if user is None:
            if password is None:  # unreachable: handled by the invitation branch above
                raise RuntimeError("owner password missing")
            user = User(
                email=email, password_hash=hash_password(password), is_active=True, is_verified=True
            )
            s.add(user)
            await s.flush()  # need user.id for the membership
            status: OwnerStatus = "created"
        else:
            # B04 D1/D2: one organization per user; platform admins stay outside.
            if user.is_platform_admin:
                raise Conflict(f"{email} is a platform administrator and cannot own a tenant")
            other = await s.scalar(
                select(OrgMembership.id).where(
                    OrgMembership.user_id == user.id, OrgMembership.org_id != org.id
                )
            )
            if other is not None:
                raise Conflict(f"{email} is already a member of another organization")
            status = "existing"
            if password is not None:
                # Never silently change an existing account's password.
                notes.append("owner already exists: --owner-password ignored")
            if not user.is_active:
                notes.append("owner account is INACTIVE; reactivate with set-user-status (B03)")

        await s.execute(
            insert(OrgMembership)
            .values(user_id=user.id, org_id=org.id, status="active")
            # B04: unique key is user_id alone; the other-org case was refused above.
            .on_conflict_do_update(index_elements=["user_id"], set_={"status": "active"})
        )
        user_id = user.id

    # The tenant role lives in the tenant schema (separate session/transaction).
    async with tenant_session(org.schema_name) as ts:
        role_id = await ts.scalar(select(Role.id).where(Role.key == OWNER_ROLE))
        if role_id is None:
            raise RuntimeError("owner role missing; seeding did not run")
        await ts.execute(
            insert(UserRole).values(user_id=user_id, role_id=role_id).on_conflict_do_nothing()
        )
    return status, None, notes


async def provision_tenant(
    slug: str,
    name: str,
    owner_email: str,
    *,
    owner_password: str | None = None,
    actor: str,
    frontend_url: str,
) -> ProvisionResult:
    """Create (or resume creating) a tenant. See module docstring."""
    slug = _validate_inputs(slug, name, owner_email, owner_password)
    owner_email = owner_email.strip().lower()
    schema = schema_for(slug)
    bound = log.bind(slug=slug, schema=schema)

    # ---- step 2: organizations row (insert or resume) ------------------------
    async with db.get_session_factory()() as s, s.begin():
        org = await s.scalar(select(Organization).where(Organization.slug == slug))
        if org is not None and org.name != name:
            raise Conflict(f"slug {slug!r} already belongs to organization {org.name!r}")
        if org is not None and org.status == "active":
            bound.info("provision.already_active")
            return ProvisionResult(org.id, slug, schema, "already_active", "skipped")
        if org is not None and org.status == "suspended":
            raise Conflict(f"organization {slug!r} is suspended; use activate-org")
        if org is None:
            org = Organization(name=name, slug=slug, schema_name=schema, status="provisioning")
            s.add(org)
            await s.flush()
            outcome: Outcome = "created"
        else:
            org.status = "provisioning"  # was 'provisioning' or 'failed': resume
            outcome = "resumed"
    bound = bound.bind(org_id=str(org.id), outcome=outcome)
    bound.info("provision.org_row_ready")

    created_schema = False
    try:
        # ---- step 3: schema ---------------------------------------------------
        if not await _schema_exists(schema):
            async with db.get_engine().begin() as conn:
                # Identifier from schema_for(): validated, safe to quote+interpolate.
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created_schema = True
        bound.info("provision.schema_ready", created=created_schema)

        # ---- step 4: tenant migrations ----------------------------------------
        await migrations.upgrade_tenant(schema)

        # ---- step 5: seed -------------------------------------------------------
        async with tenant_session(schema) as ts:
            seed = await seed_tenant(ts, name)

        # ---- step 6: owner ------------------------------------------------------
        owner_status, invite_url, notes = await _ensure_owner(
            org, owner_email, owner_password, frontend_url
        )
        bound.info("provision.owner_ready", owner_status=owner_status)

        # ---- step 7: activate + audit ------------------------------------------
        await _set_status(org.id, "active")
        audit.record(
            "org.created",
            entity="organization",
            entity_id=str(org.id),
            org=slug,
            actor=actor,
            diff={"owner_email": owner_email, "owner_status": owner_status, "outcome": outcome},
            sensitive=True,
        )
        bound.info("provision.done")
        return ProvisionResult(org.id, slug, schema, outcome, owner_status, invite_url, seed, notes)

    except Exception as exc:
        bound.error(
            "provision.failed",
            error=f"{type(exc).__name__}: {exc}",
            step_schema_created=created_schema,
        )
        try:
            await _set_status(org.id, "failed")
            if created_schema:
                async with db.get_engine().begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                bound.warning("provision.schema_dropped")
            audit.record(
                "org.provision_failed",
                entity="organization",
                entity_id=str(org.id),
                org=slug,
                actor=actor,
                result="error",
                diff={"error": f"{type(exc).__name__}: {exc}"[:500]},
            )
        except Exception:
            # Cleanup failure must not hide the original error.
            bound.exception("provision.cleanup_failed")
        raise
