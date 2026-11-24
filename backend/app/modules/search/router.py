"""HTTP surface of the search module (api_spec.md §7, design B07 §3.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import TenantAccess, require, tenant_db
from app.modules.search import service
from app.modules.search.schemas import SearchHit

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=Page[SearchHit])
async def search(
    access: Annotated[TenantAccess, Depends(require("search:use"))],
    ts: Annotated[AsyncSession, Depends(tenant_db)],
    page: Annotated[PageParams, Depends(page_params)],
    q: Annotated[
        str,
        Query(
            min_length=service.MIN_Q_LEN, max_length=service.MAX_Q_LEN, description="search text"
        ),
    ],
    types: Annotated[
        str | None,
        Query(description="comma-separated, e.g. files,items (default: all you may read)"),
    ] = None,
) -> Page[SearchHit]:
    items, total = await service.search(ts, access, q, types, page)
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)
