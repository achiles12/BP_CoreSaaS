"""Platform administration API (design B04 §3.7, api_spec.md §10).

Kept deliberately small: heavy lifting is the CLI and SQL. No X-Tenant;
only users with is_platform_admin (403 otherwise).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import require_platform_admin
from app.core.security import CurrentUser
from app.models.public import Organization, OrgMembership, User

router = APIRouter(prefix="/platform", tags=["platform"])

AdminDep = Annotated[CurrentUser, Depends(require_platform_admin)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class PlatformOrg(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    status: str
    plan: str
    members_active: int
    created_at: datetime


class PlatformStats(BaseModel):
    """Placeholder for the platform dashboard (deliverables: dashboards Phase 2-3)."""

    orgs_by_status: dict[str, int]
    users_total: int
    users_active: int
    platform_admins: int


@router.get("/orgs", response_model=list[PlatformOrg])
async def platform_orgs(_: AdminDep, s: SessionDep) -> list[PlatformOrg]:
    members = (
        select(func.count())
        .where(OrgMembership.org_id == Organization.id, OrgMembership.status == "active")
        .scalar_subquery()
    )
    rows = (await s.execute(select(Organization, members).order_by(Organization.slug))).all()
    return [
        PlatformOrg(
            id=o.id,
            slug=o.slug,
            name=o.name,
            status=o.status,
            plan=o.plan,
            members_active=n,
            created_at=o.created_at,
        )
        for o, n in rows
    ]


@router.get("/stats", response_model=PlatformStats)
async def platform_stats(_: AdminDep, s: SessionDep) -> PlatformStats:
    rows = await s.execute(select(Organization.status, func.count()).group_by(Organization.status))
    by_status = {status: count for status, count in rows.all()}
    users_total = await s.scalar(select(func.count()).select_from(User)) or 0
    users_active = await s.scalar(select(func.count()).where(User.is_active.is_(True))) or 0
    admins = await s.scalar(select(func.count()).where(User.is_platform_admin.is_(True))) or 0
    return PlatformStats(
        orgs_by_status=by_status,
        users_total=users_total,
        users_active=users_active,
        platform_admins=admins,
    )
