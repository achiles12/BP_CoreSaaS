"""Users, /me and invitations endpoints (design B04 §3.4, api_spec.md §3–4).

Routers parse and delegate; rules live in service.py. Tenant routes take
`require(<key>)` (403 when missing) plus a tenant-bound session.
"""

import uuid
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.db import get_session
from app.core.pagination import ListQuery, Page, list_query, openapi_params
from app.core.permissions import TenantAccess, require, tenant_db
from app.core.security import CurrentUser, current_user, request_settings
from app.models.public import User
from app.modules.auth.schemas import UserOut
from app.modules.users import service
from app.modules.users.schemas import (
    InvitationOut,
    InviteCreatedOut,
    InviteIn,
    MemberOut,
    MeOut,
    NameIn,
)

router = APIRouter(tags=["users"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]


def _redis(request: Request) -> ArqRedis | None:
    return getattr(request.app.state, "redis", None)


# --------------------------------------------------------------------------- #
# /me (auth only; works for unverified users and without X-Tenant: D4, D14)
# --------------------------------------------------------------------------- #
@router.get("/me", response_model=MeOut)
async def me(
    request: Request,
    caller: Annotated[CurrentUser, Depends(current_user)],
    s: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(request_settings)],
) -> MeOut:
    return await service.get_me(
        s, _redis(request), caller.user, request.headers.get(settings.tenant_header)
    )


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: NameIn,
    caller: Annotated[CurrentUser, Depends(current_user)],
    s: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    return UserOut.model_validate(await service.update_me(s, caller.user, body.full_name))


# --------------------------------------------------------------------------- #
# members
# --------------------------------------------------------------------------- #
@router.get(
    "/users",
    response_model=Page[MemberOut],
    openapi_extra=openapi_params(service.USERS_LIST),
)
async def list_users(
    access: Annotated[TenantAccess, Depends(require("users:read"))],
    ts: TenantDb,
    lq: Annotated[ListQuery, Depends(list_query(service.USERS_LIST, User.id))],
    q: Annotated[str | None, Query(max_length=100, description="email / name contains")] = None,
    # Pre-B06 parameter, kept for the B09 dashboard cards (B06 D9). Same as filter[status].
    member_status: Annotated[
        str | None, Query(alias="status", pattern="^(active|inactive)$")
    ] = None,
) -> Page[MemberOut]:
    items, total = await service.list_members(ts, access.tenant.org_id, q, member_status, lq)
    return Page(items=items, total=total, page=lq.page.page, page_size=lq.page.page_size)


@router.get("/users/{user_id}", response_model=MemberOut)
async def get_user(
    user_id: uuid.UUID,
    access: Annotated[TenantAccess, Depends(require("users:read"))],
    ts: TenantDb,
) -> MemberOut:
    return await service.get_member(ts, access.tenant.org_id, user_id)


@router.patch("/users/{user_id}", response_model=MemberOut)
async def update_user(
    user_id: uuid.UUID,
    body: NameIn,
    access: Annotated[TenantAccess, Depends(require("users:update"))],
    ts: TenantDb,
) -> MemberOut:
    return await service.update_member(ts, access, user_id, body.full_name)


@router.post("/users/{user_id}/deactivate", response_model=MemberOut)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    access: Annotated[TenantAccess, Depends(require("users:deactivate"))],
    ts: TenantDb,
) -> MemberOut:
    return await service.set_member_active(ts, _redis(request), access, user_id, False)


@router.post("/users/{user_id}/activate", response_model=MemberOut)
async def activate_user(
    user_id: uuid.UUID,
    request: Request,
    access: Annotated[TenantAccess, Depends(require("users:deactivate"))],
    ts: TenantDb,
) -> MemberOut:
    return await service.set_member_active(ts, _redis(request), access, user_id, True)


# --------------------------------------------------------------------------- #
# invitations
# --------------------------------------------------------------------------- #
@router.post("/users/invite", response_model=InviteCreatedOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteIn,
    request: Request,
    access: Annotated[TenantAccess, Depends(require("users:invite"))],
    ts: TenantDb,
    settings: Annotated[Settings, Depends(request_settings)],
) -> InviteCreatedOut:
    created = await service.create_invitation(
        ts,
        _redis(request),
        tenant=access.tenant,
        email=body.email,
        role_key=body.role_key,
        inviter=access.user,
        inviter_rank=access.rank,
        actor=str(access.user_id),
        frontend_url=settings.frontend_url,
    )
    return InviteCreatedOut(
        invitation=service.invitation_out(created.invitation, access.user.email),
        email_queued=created.job_id is not None,
    )


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(
    access: Annotated[TenantAccess, Depends(require("users:invite"))],
    ts: TenantDb,
) -> list[InvitationOut]:
    return await service.list_invitations(ts, access.tenant.org_id)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    access: Annotated[TenantAccess, Depends(require("users:invite"))],
    ts: TenantDb,
) -> None:
    await service.revoke_invitation(ts, access, invitation_id)
