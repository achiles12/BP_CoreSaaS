"""Items as an export source (design B07 §3.4, §3.6). COPYING: rename with the module.

Uses the SAME statement as GET /items (service.items_statement), so the file
has exactly the rows the list shows for the same query.
"""

from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules._template.models import TemplateItem
from app.modules._template.service import ITEMS_LIST, items_statement
from app.modules.exports.sources import ExportContext, ExportSource, ParsedFilters, register

COLUMNS = [
    "id",
    "title",
    "description",
    "status",
    "owner_id",
    "owner_name",
    "created_at",
    "updated_at",
]


def _statement(_ctx: ExportContext, f: ParsedFilters) -> Select:
    return items_statement(f.q, f.lq)


async def _rows(_ts: AsyncSession, batch: list[Any]) -> list[list[Any]]:
    out = []
    for item, owner_name in batch:
        out.append(
            [
                item.id,
                item.title,
                item.description,
                item.status,
                item.owner_id,
                owner_name,
                item.created_at,
                item.updated_at,
            ]
        )
    return out


register(
    ExportSource(
        resource="items",
        permission="items:read",
        spec=ITEMS_LIST,
        id_column=TemplateItem.id,
        statement=_statement,
        columns=COLUMNS,
        rows=_rows,
    )
)
