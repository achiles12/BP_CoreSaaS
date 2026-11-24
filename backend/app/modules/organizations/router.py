"""Organization endpoints (design B04 §3.6, api_spec.md §3)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.permissions import TenantAccess, require, tenant_db
from app.core.security import CurrentUser, current_user
from app.modules.organizations import service
from app.modules.organizations.schemas import OrgListItem, OrgOut, OrgUpdateIn

router = APIRouter(tags=["organizations"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]


@router.get("/orgs", response_model=list[OrgListItem])
async def list_orgs(
    caller: Annotated[CurrentUser, Depends(current_user)],
    s: Annotated[AsyncSession, Depends(get_session)],
) -> list[OrgListItem]:
    return await service.list_orgs(s, caller.user)


@router.get("/org", response_model=OrgOut)
async def get_org(
    access: Annotated[TenantAccess, Depends(require("org:read"))], ts: TenantDb
) -> OrgOut:
    return await service.get_org(ts, access)


@router.patch("/org", response_model=OrgOut)
async def update_org(
    body: OrgUpdateIn,
    access: Annotated[TenantAccess, Depends(require("org:update"))],
    ts: TenantDb,
) -> OrgOut:
    return await service.update_org(ts, access, body.name, body.display_name)
