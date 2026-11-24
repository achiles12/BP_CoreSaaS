"""Global search (design B07 §3.3, D10; backend_processes.md §7).

One UNION ALL over the sources the caller may read, ranked by score. Runs in
the caller's tenant session, so other tenants' rows cannot appear (C2).
"""

import structlog
from sqlalchemy import Select, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.core.pagination import PageParams, paginate
from app.core.permissions import TenantAccess
from app.modules.search.schemas import SearchHit
from app.modules.search.sources import sources

log = structlog.get_logger("app.search")

MIN_Q_LEN = 2
MAX_Q_LEN = 100


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed(f"{field}: {message}", fields=[{"field": field, "message": message}])


def pick_types(access: TenantAccess, raw: str | None) -> list[str]:
    """Requested types (default: all) minus those the caller cannot read (D10).

    An UNKNOWN type is a 422 (a client bug); a known one without permission is
    silently left out, so the UI can always ask for everything.
    """
    known = sources()
    wanted = [t.strip() for t in (raw or "").split(",") if t.strip()] or sorted(known)
    unknown = [t for t in wanted if t not in known]
    if unknown:
        raise _invalid(
            "types", f"unknown type(s) {', '.join(unknown)}; allowed: {', '.join(sorted(known))}"
        )
    return [t for t in dict.fromkeys(wanted) if known[t].permission in access.permissions]


async def search(
    ts: AsyncSession, access: TenantAccess, q: str, types: str | None, page: PageParams
) -> tuple[list[SearchHit], int]:
    q = " ".join(q.split())
    if len(q) < MIN_Q_LEN:
        raise _invalid("q", f"at least {MIN_Q_LEN} characters")
    allowed = pick_types(access, types)
    if not allowed:
        log.info("search.no_types", org=access.tenant.slug, requested=types)
        return [], 0
    known = sources()
    parts = [known[t].build(q).add_columns(literal(t).label("type")) for t in allowed]
    u = union_all(*parts).subquery("hits")
    stmt: Select = select(u.c.type, u.c.id, u.c.title, u.c.snippet, u.c.score).order_by(
        u.c.score.desc(), u.c.type, u.c.id
    )
    rows, total = await paginate(ts, stmt, page)
    log.info("search.done", org=access.tenant.slug, types=allowed, total=total)
    return [
        SearchHit(type=r.type, id=r.id, title=r.title, snippet=r.snippet, score=round(r.score, 4))
        for r in rows
    ], total
