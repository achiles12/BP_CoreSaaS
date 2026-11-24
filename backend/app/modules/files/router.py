"""Files endpoints (design B05 §3.4, api_spec.md §6).

Routers parse and delegate; rules live in service.py. Every route needs a
permission (`require`, 403 when missing) and runs in the tenant session.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.pagination import ListQuery, Page, list_query, openapi_params
from app.core.permissions import TenantAccess, require, tenant_db
from app.core.security import request_settings
from app.models.tenant import File
from app.modules.files import service
from app.modules.files.schemas import DownloadOut, FileOut, PresignIn, PresignOut

router = APIRouter(prefix="/files", tags=["files"])

TenantDb = Annotated[AsyncSession, Depends(tenant_db)]
AppSettings = Annotated[Settings, Depends(request_settings)]


@router.post("/presign-upload", response_model=PresignOut, status_code=status.HTTP_201_CREATED)
async def presign_upload(
    body: PresignIn,
    access: Annotated[TenantAccess, Depends(require("files:write"))],
    ts: TenantDb,
    settings: AppSettings,
) -> PresignOut:
    return await service.presign_upload(ts, settings, access, body)


@router.post("/{file_id}/confirm", response_model=FileOut)
async def confirm_upload(
    file_id: uuid.UUID,
    access: Annotated[TenantAccess, Depends(require("files:write"))],
    ts: TenantDb,
    settings: AppSettings,
) -> FileOut:
    return await service.confirm_upload(ts, settings, access, file_id)


@router.get("", response_model=Page[FileOut], openapi_extra=openapi_params(service.FILES_LIST))
async def list_files(
    access: Annotated[TenantAccess, Depends(require("files:read"))],
    ts: TenantDb,
    lq: Annotated[ListQuery, Depends(list_query(service.FILES_LIST, File.id))],
    q: Annotated[str | None, Query(max_length=100, description="name contains")] = None,
    mine: Annotated[bool, Query(description="only files I uploaded")] = False,
) -> Page[FileOut]:
    items, total = await service.list_files(ts, access, q, mine, lq)
    return Page(items=items, total=total, page=lq.page.page, page_size=lq.page.page_size)


@router.get("/{file_id}", response_model=FileOut)
async def get_file(
    file_id: uuid.UUID,
    _: Annotated[TenantAccess, Depends(require("files:read"))],
    ts: TenantDb,
) -> FileOut:
    return await service.get_file(ts, file_id)


@router.get("/{file_id}/download-url", response_model=DownloadOut)
async def download_url(
    file_id: uuid.UUID,
    access: Annotated[TenantAccess, Depends(require("files:read"))],
    ts: TenantDb,
    settings: AppSettings,
) -> DownloadOut:
    return await service.download_url(ts, settings, access, file_id)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    access: Annotated[TenantAccess, Depends(require("files:delete"))],
    ts: TenantDb,
) -> None:
    await service.delete_file(ts, access, file_id)
