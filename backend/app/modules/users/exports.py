"""Members as an export source (design B07 §3.4, §3.6): same query as GET /users.

Columns are MemberOut's fields; roles are joined with ";" (one cell).
"""

from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.public import User
from app.modules.exports.sources import ExportContext, ExportSource, ParsedFilters, register
from app.modules.users.service import USERS_LIST, members_statement, roles_of

COLUMNS = ["id", "email", "full_name", "status", "is_verified", "roles", "joined_at"]
MEMBER_STATUSES = ("active", "inactive")


def _status(value: str) -> str | None:
    v = value.strip()
    if v and v not in MEMBER_STATUSES:
        raise ValueError(f"must be one of {', '.join(MEMBER_STATUSES)}")
    return v or None


def _statement(ctx: ExportContext, f: ParsedFilters) -> Select:
    return members_statement(ctx.org_id, f.q, f.extras.get("status"), f.lq)


async def _rows(ts: AsyncSession, batch: list[Any]) -> list[list[Any]]:
    roles = await roles_of(ts, [u.id for u, _m in batch])  # one query per batch
    return [
        [
            u.id,
            u.email,
            u.full_name,
            m.status,
            u.is_verified,
            ";".join(r.key for r in roles[u.id]),
            m.created_at,
        ]
        for u, m in batch
    ]


register(
    ExportSource(
        resource="users",
        permission="users:read",
        spec=USERS_LIST,
        id_column=User.id,
        statement=_statement,
        columns=COLUMNS,
        rows=_rows,
        extras={"status": _status},
    )
)
