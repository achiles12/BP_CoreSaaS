"""HTTP surface of the notifications module (api_spec.md §9, design B07 §3.7).

All three routes need `notifications:read` (every tenant role has it); the
service limits every query to the caller's own rows.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import TenantAccess, require, tenant_db
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationOut, ReadAllOut

router = APIRouter(prefix="/notifications", tags=["notifications"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]
CanRead = Annotated[TenantAccess, Depends(require("notifications:read"))]


@router.get("", response_model=Page[NotificationOut])
async def list_notifications(
    access: CanRead,
    ts: TenantDb,
    page: Annotated[PageParams, Depends(page_params)],
    unread: Annotated[bool, Query(description="only notifications not yet read")] = False,
) -> Page[NotificationOut]:
    items, total = await service.list_notifications(ts, access, unread, page)
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


# Declared before /{notification_id}/read so "read-all" is never taken for an id.
@router.post("/read-all", response_model=ReadAllOut)
async def mark_all_notifications_read(access: CanRead, ts: TenantDb) -> ReadAllOut:
    return ReadAllOut(updated=await service.mark_all_read(ts, access))


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: uuid.UUID, access: CanRead, ts: TenantDb
) -> NotificationOut:
    return await service.mark_read(ts, access, notification_id)
