"""Organization reads/updates (design B04 §3.6, D3, D16)."""

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.errors import NotFound
from app.core.permissions import TenantAccess
from app.models.public import Organization, OrgMembership, User
from app.models.tenant import Setting
from app.modules.organizations.schemas import OrgListItem, OrgOut

log = structlog.get_logger("app.organizations")

DISPLAY_NAME_KEY = "app.display_name"  # seeded by provisioning (rbac/seed.py)


async def list_orgs(s: AsyncSession, user: User) -> list[OrgListItem]:
    """The user's organization (one at most, D1); platform admins see all."""
    stmt = select(Organization).order_by(Organization.name)
    if not user.is_platform_admin:
        stmt = stmt.join(OrgMembership, OrgMembership.org_id == Organization.id).where(
            OrgMembership.user_id == user.id,
            OrgMembership.status == "active",
            Organization.status == "active",
        )
    orgs = (await s.scalars(stmt)).all()
    return [OrgListItem(id=o.id, slug=o.slug, name=o.name, status=o.status) for o in orgs]


async def _org_and_display(
    ts: AsyncSession, access: TenantAccess
) -> tuple[Organization, str | None]:
    org = await ts.get(Organization, access.tenant.org_id)
    if org is None:  # deleted between resolve and read: practically impossible
        raise NotFound("Organization not found")
    display = await ts.scalar(select(Setting.value).where(Setting.key == DISPLAY_NAME_KEY))
    return org, display if isinstance(display, str) else None


def _out(org: Organization, display: str | None) -> OrgOut:
    return OrgOut(
        id=org.id,
        slug=org.slug,
        name=org.name,
        display_name=display,
        status=org.status,
        plan=org.plan,
        created_at=org.created_at,
    )


async def get_org(ts: AsyncSession, access: TenantAccess) -> OrgOut:
    return _out(*await _org_and_display(ts, access))


async def update_org(
    ts: AsyncSession, access: TenantAccess, name: str | None, display_name: str | None
) -> OrgOut:
    org, display = await _org_and_display(ts, access)
    diff: dict[str, list[str | None]] = {}
    if name is not None and name != org.name:
        diff["name"] = [org.name, name]
        org.name = name
    if display_name is not None and display_name != display:
        diff["display_name"] = [display, display_name]
        await ts.execute(
            insert(Setting)
            .values(key=DISPLAY_NAME_KEY, value=display_name, updated_by=access.user_id)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": display_name, "updated_by": access.user_id},
            )
        )
        display = display_name
    if diff:
        await ts.commit()
        audit.record(
            "org.update",
            entity="organization",
            entity_id=str(org.id),
            org=org.slug,
            actor=str(access.user_id),
            diff=diff,
        )
        log.info("organizations.updated", fields=sorted(diff))
    return _out(org, display)
