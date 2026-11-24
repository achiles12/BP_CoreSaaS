"""Demo organization and users for a fresh clone (design B13 D8).

`cli init` calls this on every `docker compose up` in dev, so it must be safe
to repeat: it only ever CREATES what is missing. A demo user that already
exists is never touched (password, role, status and membership stay as they
are), so people can change the demo data without `up` undoing it.

Dev only: the password below is public. The CLI refuses other environments.
"""

from dataclasses import dataclass, field

import structlog
from sqlalchemy import select

from app.config import Settings
from app.core import audit, db
from app.core.security import hash_password, verify_password
from app.core.tenancy import tenant_session
from app.models.public import OrgMembership, User
from app.models.tenant import Role, UserRole
from app.modules.organizations.provisioning import provision_tenant

log = structlog.get_logger("app.demo_seed")

DEMO_SLUG = "demo"
DEMO_NAME = "Demo Org"
DEMO_PASSWORD = "Demo-pass-2026-ok"  # noqa: S105 (documented dev-only password)
DEMO_OWNER = "owner@demo.test"
# email -> (role key, full name). The owner is created by provision_tenant.
DEMO_MEMBERS: dict[str, tuple[str, str]] = {
    DEMO_OWNER: ("owner", "Demo Owner"),
    "admin@demo.test": ("admin", "Demo Admin"),
    "manager@demo.test": ("manager", "Demo Manager"),
    "staff@demo.test": ("staff", "Demo Staff"),
    "user@demo.test": ("user", "Demo User"),
}
DEMO_PLATFORM = "platform@demo.test"


@dataclass
class SeedResult:
    outcome: str  # provisioning outcome: created / resumed / already_active
    users_added: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def seed_demo(settings: Settings, actor: str) -> SeedResult:
    """Create the demo org and its missing users. Raises AppError on a conflict
    with the org itself (slug taken by another org, org suspended)."""
    org = await provision_tenant(
        DEMO_SLUG,
        DEMO_NAME,
        DEMO_OWNER,
        owner_password=DEMO_PASSWORD,
        actor=actor,
        frontend_url=settings.frontend_url,
    )
    result = SeedResult(outcome=org.outcome)

    created: list[User] = []
    # One transaction for public AND tenant rows: a crash must not leave a user
    # without a role, because existing users are never repaired later.
    async with tenant_session(org.schema_name) as s:
        roles = {r.key: r.id for r in (await s.scalars(select(Role))).all()}
        for email, (role, name) in DEMO_MEMBERS.items():
            user = await s.scalar(select(User).where(User.email == email))
            if user is not None:
                elsewhere = await s.scalar(
                    select(OrgMembership.id).where(
                        OrgMembership.user_id == user.id, OrgMembership.org_id != org.org_id
                    )
                )
                if elsewhere is not None:
                    result.warnings.append(f"{email} belongs to another organization; left as is")
                continue
            if role not in roles:
                result.warnings.append(f"role {role!r} is missing; {email} not created")
                continue
            user = _new_user(email, name)
            s.add(user)
            await s.flush()  # need user.id
            s.add(OrgMembership(user_id=user.id, org_id=org.org_id, status="active"))
            s.add(UserRole(user_id=user.id, role_id=roles[role]))
            created.append(user)
        if await s.scalar(select(User.id).where(User.email == DEMO_PLATFORM)) is None:
            platform = _new_user(DEMO_PLATFORM, "Demo Platform Admin")
            platform.is_platform_admin = True
            s.add(platform)
            await s.flush()
            created.append(platform)
        rows = [(str(u.id), u.email, u.is_platform_admin) for u in created]

    for user_id, email, is_platform in rows:
        result.users_added.append(email)
        audit.record(
            "user.created",
            entity="user",
            entity_id=user_id,
            org=None if is_platform else DEMO_SLUG,
            actor=actor,
            diff={"email": email, "is_platform_admin": is_platform, "source": "demo-seed"},
            sensitive=True,
        )
    log.info("demo_seed.done", outcome=org.outcome, users_added=len(rows))
    return result


async def active_demo_logins() -> list[str]:
    """Emails of active demo users that still have the public demo password."""
    async with db.get_session_factory()() as s:
        users = (
            await s.scalars(
                select(User)
                .where(User.email.in_([*DEMO_MEMBERS, DEMO_PLATFORM]), User.is_active.is_(True))
                .order_by(User.email)
            )
        ).all()
    return [
        u.email
        for u in users
        if u.password_hash and verify_password(DEMO_PASSWORD, u.password_hash)
    ]


def _new_user(email: str, name: str) -> User:
    return User(
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
        full_name=name,
        is_active=True,
        is_verified=True,
        is_platform_admin=False,
    )
