"""HTTP surface of the template module (api_spec.md §11, design B06 §3.4).

Routers only parse and delegate. Every route has a permission (`require`,
403 when missing) and a tenant-bound session (X-Tenant + membership check).

COPYING: route function names become OpenAPI operationIds and frontend hook
names (useListItems, ...), and must be unique across ALL modules
(tests/test_openapi_ids.py). Rename them with the module.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import ListQuery, Page, list_query, openapi_params
from app.core.permissions import TenantAccess, require, tenant_db
from app.modules._template import service
from app.modules._template.models import TemplateItem
from app.modules._template.schemas import ItemCreate, ItemOut, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]


@router.get("", response_model=Page[ItemOut], openapi_extra=openapi_params(service.ITEMS_LIST))
async def list_items(
    _: Annotated[TenantAccess, Depends(require("items:read"))],
    ts: TenantDb,
    lq: Annotated[ListQuery, Depends(list_query(service.ITEMS_LIST, TemplateItem.id))],
    q: Annotated[str | None, Query(max_length=100, description="title contains")] = None,
) -> Page[ItemOut]:
    items, total = await service.list_items(ts, q, lq)
    return Page(items=items, total=total, page=lq.page.page, page_size=lq.page.page_size)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: ItemCreate,
    access: Annotated[TenantAccess, Depends(require("items:write"))],
    ts: TenantDb,
) -> ItemOut:
    return await service.create_item(ts, access, body)


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: uuid.UUID,
    _: Annotated[TenantAccess, Depends(require("items:read"))],
    ts: TenantDb,
) -> ItemOut:
    return await service.get_item(ts, item_id)


@router.patch("/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    access: Annotated[TenantAccess, Depends(require("items:write"))],
    ts: TenantDb,
) -> ItemOut:
    return await service.update_item(ts, access, item_id, body)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    access: Annotated[TenantAccess, Depends(require("items:delete"))],
    ts: TenantDb,
) -> None:
    await service.delete_item(ts, access, item_id)
