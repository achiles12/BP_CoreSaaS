"""List helpers: paging, sorting, filtering (design B04 D17, B06 §3.1, D6–D8).

Query conventions (api_spec.md):
    ?page=1&page_size=25              page_size capped at 100
    ?sort=-created_at,name            "-" = descending, at most 3 fields
    ?filter[status]=open              equals; "a,b" = any of
    ?filter[created_at][gte]=...      ranges on date/number fields that allow them
Responses: `{items, total, page, page_size}`.

Each list declares a `ListSpec` naming the ONLY fields that may be sorted or
filtered, so user input never reaches SQL as a column name. Anything else is a
422 that lists what is allowed. `parse_filters` is shared with exports (B07),
so an export returns exactly the rows the list shows.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description=f"items per page (max {MAX_PAGE_SIZE})")
    ] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    """FastAPI dependency: validated page params (422 when out of range)."""
    return PageParams(page=page, page_size=page_size)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


async def paginate(
    session: AsyncSession, stmt: Select[Any], params: PageParams
) -> tuple[list[Any], int]:
    """Run `stmt` for one page and count all matching rows.

    The count wraps the UNPAGED statement as a subquery, so joins/filters are
    counted exactly as listed. `stmt` must already carry a deterministic ORDER BY.
    """
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await session.execute(stmt.limit(params.page_size).offset(params.offset))).all()
    return list(rows), int(total or 0)


# --------------------------------------------------------------------------- #
# sort + filter (B06)
# --------------------------------------------------------------------------- #
MAX_SORT_FIELDS = 3
FilterKind = Literal["text", "enum", "uuid", "int", "datetime"]
RANGE_OPS = ("gte", "lte")
# filter[<field>] or filter[<field>][<op>]; anything else starting with "filter" is a 422.
_FILTER_KEY = re.compile(r"^filter\[([a-z_][a-z0-9_]*)\](?:\[([a-z]+)\])?$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-?([0-9a-fA-F]{4}-?){3}[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class FilterField:
    """One filterable field of a list (D7)."""

    column: Any  # a SQLAlchemy column / mapped attribute
    kind: FilterKind
    choices: tuple[str, ...] = ()  # allowed values for kind="enum"
    ranges: bool = False  # also accept [gte] / [lte]


@dataclass(frozen=True)
class ListSpec:
    """What one list endpoint allows (D8)."""

    sort: dict[str, Any]  # public name -> column
    default_sort: str  # e.g. "-created_at"
    filters: dict[str, FilterField] = field(default_factory=dict)


@dataclass(frozen=True)
class ListQuery:
    """A parsed list request: apply `where` and `order_by`, then paginate."""

    page: PageParams
    order_by: list[Any]
    where: list[Any]

    def apply[*Ts](self, stmt: Select[*Ts]) -> Select[*Ts]:
        """Add the WHERE and ORDER BY clauses; keeps the statement's row type."""
        return stmt.where(*self.where).order_by(*self.order_by)


def _invalid(param: str, message: str) -> ValidationFailed:
    return ValidationFailed(f"{param}: {message}", fields=[{"field": param, "message": message}])


def parse_sort(spec: ListSpec, raw: str | None, id_column: Any) -> list[Any]:
    """`-a,b` -> [a DESC, b ASC, id ASC]. Empty -> the spec's default (D6).

    The id is always appended so rows with equal sort values keep a stable
    order across pages.
    """
    names = [n.strip() for n in (raw or "").split(",") if n.strip()]
    if not names:
        names = [n.strip() for n in spec.default_sort.split(",") if n.strip()]
    if len(names) > MAX_SORT_FIELDS:
        raise _invalid("sort", f"at most {MAX_SORT_FIELDS} fields")
    seen: set[str] = set()
    clauses = []
    for name in names:
        desc = name.startswith("-")
        bare = name.lstrip("-")
        if bare not in spec.sort:
            raise _invalid(
                "sort", f"cannot sort by {bare!r}; allowed: {', '.join(sorted(spec.sort))}"
            )
        if bare in seen:
            raise _invalid("sort", f"{bare!r} given twice")
        seen.add(bare)
        col = spec.sort[bare]
        clauses.append(col.desc() if desc else col.asc())
    clauses.append(id_column.asc())
    return clauses


def _parse_datetime(value: str, op: str, param: str) -> tuple[str, datetime]:
    """ISO date or datetime -> aware datetime. A date-only upper bound covers that day.

    Returns the operator actually used: "lte" with a bare date becomes "<" the next day.
    """
    try:
        if len(value) == 10:  # YYYY-MM-DD
            d = date.fromisoformat(value)
            start = datetime(d.year, d.month, d.day, tzinfo=UTC)
            return ("lt", start + timedelta(days=1)) if op == "lte" else (op, start)
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(param, "expected an ISO date or datetime") from exc
    return op, dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # naive = UTC


def _convert(ff: FilterField, value: str, param: str) -> Any:
    if ff.kind == "enum":
        if value not in ff.choices:
            raise _invalid(param, f"must be one of {', '.join(ff.choices)}")
        return value
    if ff.kind == "uuid":
        if not _UUID.fullmatch(value):
            raise _invalid(param, "expected a UUID")
        return uuid.UUID(value)
    if ff.kind == "int":
        try:
            return int(value)
        except ValueError as exc:
            raise _invalid(param, "expected a whole number") from exc
    return value  # text: exact match


def parse_filters(spec: ListSpec, raw: dict[str, str]) -> list[Any]:
    """`{"filter[status]": "a,b", "filter[x][gte]": "1"}` -> WHERE clauses (D7).

    Keys that do not start with "filter" are ignored (page, q, sort, ...).
    Empty values are ignored, so a blank form field means "no filter".
    """
    clauses = []
    for key, value in raw.items():
        if not key.startswith("filter"):
            continue
        m = _FILTER_KEY.fullmatch(key)
        if not m:
            raise _invalid(key, "expected filter[field] or filter[field][gte|lte]")
        name, op = m.group(1), m.group(2)
        ff = spec.filters.get(name)
        if ff is None:
            allowed = ", ".join(sorted(spec.filters)) or "none"
            raise _invalid(key, f"cannot filter by {name!r}; allowed: {allowed}")
        if op is not None and (op not in RANGE_OPS or not ff.ranges):
            raise _invalid(key, f"operator {op!r} not allowed here")
        if ff.kind == "datetime" and op is None:
            raise _invalid(key, "use [gte] and/or [lte] for dates")
        values = [v.strip() for v in value.split(",") if v.strip()]
        if not values:
            continue
        if op is not None:
            if len(values) != 1:
                raise _invalid(key, "a range takes one value")
            if ff.kind == "datetime":
                real_op, bound = _parse_datetime(values[0], op, key)
            else:
                real_op, bound = op, _convert(ff, values[0], key)
            col = ff.column
            clauses.append({"gte": col >= bound, "lte": col <= bound, "lt": col < bound}[real_op])
            continue
        converted = [_convert(ff, v, key) for v in values]
        clauses.append(
            ff.column == converted[0] if len(converted) == 1 else ff.column.in_(converted)
        )
    return clauses


def list_query(spec: ListSpec, id_column: Any) -> Callable[..., ListQuery]:
    """FastAPI dependency: page params + `sort` + every `filter[...]` (422 on bad input)."""

    def dependency(
        request: Request, page: Annotated[PageParams, Depends(page_params)]
    ) -> ListQuery:
        qp = request.query_params
        filters = {k: v for k, v in qp.items() if k.startswith("filter")}
        return ListQuery(
            page=page,
            order_by=parse_sort(spec, qp.get("sort"), id_column),
            where=parse_filters(spec, filters),
        )

    return dependency


def openapi_params(spec: ListSpec) -> dict[str, Any]:
    """`openapi_extra` for a list route, so docs and the generated client show
    `sort` and each `filter[...]` parameter (FastAPI appends these to its own)."""
    params: list[dict[str, Any]] = [
        {
            "name": "sort",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "description": (
                f"comma-separated, '-' = descending, max {MAX_SORT_FIELDS}. "
                f"Fields: {', '.join(sorted(spec.sort))}. Default: {spec.default_sort}"
            ),
        }
    ]
    for name, ff in spec.filters.items():
        schema: dict[str, Any] = {"type": "string"}
        if ff.kind == "enum":
            schema["description"] = "one or more of: " + ", ".join(ff.choices)
        if ff.kind != "datetime":
            params.append(
                {
                    "name": f"filter[{name}]",
                    "in": "query",
                    "required": False,
                    "schema": schema,
                    "description": f"{ff.kind}; comma = any of",
                }
            )
        if ff.ranges:
            for op in RANGE_OPS:
                params.append(
                    {
                        "name": f"filter[{name}][{op}]",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": f"{ff.kind} {'>=' if op == 'gte' else '<='}",
                    }
                )
    return {"parameters": params}
