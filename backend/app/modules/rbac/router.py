"""RBAC endpoints (design B04 §3.5, api_spec.md §5)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import TenantAccess, require, tenant_db
from app.modules.rbac import service
from app.modules.rbac.schemas import PermissionOut, RoleKeysIn, RoleOut
from app.modules.users.schemas import MemberOut

router = APIRouter(tags=["rbac"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    _: Annotated[TenantAccess, Depends(require("roles:read"))], ts: TenantDb
) -> list[RoleOut]:
    return await service.list_roles(ts)


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    _: Annotated[TenantAccess, Depends(require("roles:read"))], ts: TenantDb
) -> list[PermissionOut]:
    return await service.list_permissions(ts)


@router.put("/users/{user_id}/roles", response_model=MemberOut)
async def set_user_roles(
    user_id: uuid.UUID,
    body: RoleKeysIn,
    request: Request,
    access: Annotated[TenantAccess, Depends(require("roles:assign"))],
    ts: TenantDb,
) -> MemberOut:
    redis = getattr(request.app.state, "redis", None)
    return await service.set_roles(ts, redis, access, user_id, body.role_keys)
