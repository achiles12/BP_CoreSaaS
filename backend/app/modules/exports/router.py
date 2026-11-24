"""HTTP surface of the exports module (api_spec.md §8, design B07 §3.4).

Every route needs `export:run`; POST also needs the resource's read key (D3).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import TenantAccess, require, tenant_db
from app.core.security import request_settings
from app.modules.exports import service
from app.modules.exports.schemas import ExportCreate, ExportOut

router = APIRouter(prefix="/exports", tags=["exports"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]
CanExport = Annotated[TenantAccess, Depends(require("export:run"))]
AppSettings = Annotated[Settings, Depends(request_settings)]


def _redis(request: Request) -> object:
    return getattr(request.app.state, "redis", None)


@router.post("", response_model=ExportOut, status_code=status.HTTP_202_ACCEPTED)
async def create_export(
    body: ExportCreate,
    access: CanExport,
    ts: TenantDb,
    settings: AppSettings,
    redis: Annotated[object, Depends(_redis)],
) -> ExportOut:
    return await service.create_export(ts, redis, settings, access, body)


@router.get("", response_model=Page[ExportOut])
async def list_exports(
    access: CanExport,
    ts: TenantDb,
    settings: AppSettings,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[ExportOut]:
    items, total = await service.list_exports(ts, settings, access, page)
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


@router.get("/{export_id}", response_model=ExportOut)
async def get_export(
    export_id: uuid.UUID, access: CanExport, ts: TenantDb, settings: AppSettings
) -> ExportOut:
    return await service.get_export(ts, settings, access, export_id)
