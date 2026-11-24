"""Files as an export source (design B07 §3.4, §3.6): same query as GET /files."""

from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import File
from app.modules.exports.sources import (
    ExportContext,
    ExportSource,
    ParsedFilters,
    parse_bool,
    register,
)
from app.modules.files.service import FILES_LIST, files_statement

COLUMNS = ["id", "name", "mime_type", "size_bytes", "uploaded_by", "uploader_name", "created_at"]


def _statement(ctx: ExportContext, f: ParsedFilters) -> Select:
    return files_statement(ctx.user_id, f.q, f.extras.get("mine", False), f.lq)


async def _rows(_ts: AsyncSession, batch: list[Any]) -> list[list[Any]]:
    return [
        [f.id, f.name, f.mime_type, f.size_bytes, f.uploaded_by, name, f.created_at]
        for f, name in batch
    ]


register(
    ExportSource(
        resource="files",
        permission="files:read",
        spec=FILES_LIST,
        id_column=File.id,
        statement=_statement,
        columns=COLUMNS,
        rows=_rows,
        extras={"mine": parse_bool},
    )
)
