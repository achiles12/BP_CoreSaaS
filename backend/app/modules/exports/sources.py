"""Exportable lists (design B07 §3.4, D4, D5, D14).

A module makes a list exportable by adding `exports.py` that calls
`register(ExportSource(...))`. The source reuses the list's ListSpec and its
statement builder, so an export returns exactly the rows the list shows for
the same query (backend_processes.md §7).

Export `filters` are the list's query parameters as a flat dict of strings:
    {"q": "...", "sort": "-title", "filter[status]": "open,done", <extras>}
`page`/`page_size` are ignored (an export is every page).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.core.pagination import ListQuery, ListSpec, PageParams, parse_filters, parse_sort
from app.modules import registry

MAX_Q_LEN = 100  # same limit as the list endpoints' `q`
IGNORED_KEYS = frozenset({"page", "page_size"})
FIXED_KEYS = frozenset({"q", "sort"})


@dataclass(frozen=True)
class ExportContext:
    """Who the export runs for. Built from the request, or from the job row."""

    user_id: uuid.UUID
    org_id: uuid.UUID
    slug: str


@dataclass(frozen=True)
class ParsedFilters:
    q: str | None
    extras: dict[str, Any]  # converted values of the list's own extra params
    lq: ListQuery


@dataclass(frozen=True)
class ExportSource:
    resource: str  # "items"; the `resource` value in POST /exports
    permission: str  # read key also required (D3), e.g. "items:read"
    spec: ListSpec  # the list's sort/filter spec
    id_column: Any  # stable tiebreak column for sort
    # (ctx, parsed) -> the list's SELECT, unpaged
    statement: Callable[[ExportContext, ParsedFilters], Select]
    columns: list[str]  # header row
    # one batch of statement rows -> one list of cell values per row
    rows: Callable[[AsyncSession, list[Any]], Awaitable[list[list[Any]]]]
    # list-specific params besides q/sort/filter[...]: name -> converter (raise ValueError)
    extras: dict[str, Callable[[str], Any]] = field(default_factory=dict)


_sources: dict[str, ExportSource] = {}


def register(src: ExportSource) -> None:
    existing = _sources.get(src.resource)
    if existing is not None and existing != src:
        raise ValueError(f"export resource {src.resource!r} registered twice")
    _sources[src.resource] = src


def sources() -> dict[str, ExportSource]:
    """Every registered source, loading the modules' exports.py files first."""
    registry.load_parts("exports")
    return dict(_sources)


def _invalid(param: str, message: str) -> ValidationFailed:
    return ValidationFailed(f"{param}: {message}", fields=[{"field": param, "message": message}])


def get_source(resource: str) -> ExportSource:
    known = sources()
    src = known.get(resource)
    if src is None:
        raise _invalid("resource", f"unknown {resource!r}; allowed: {', '.join(sorted(known))}")
    return src


def parse_bool(value: str) -> bool:
    """Query-string booleans as FastAPI reads them for the list endpoints."""
    v = value.strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off", ""):
        return False
    raise ValueError("expected true or false")


def parse_export_filters(src: ExportSource, filters: dict[str, str]) -> ParsedFilters:
    """Validate and parse with the list's own rules: 422 on anything the list would reject."""
    extras: dict[str, Any] = {}
    for key, value in filters.items():
        if key in IGNORED_KEYS or key in FIXED_KEYS or key.startswith("filter"):
            continue
        conv = src.extras.get(key)
        if conv is None:
            allowed = sorted(FIXED_KEYS | set(src.extras)) + ["filter[...]"]
            raise _invalid(
                f"filters.{key}",
                f"not a parameter of {src.resource}; allowed: {', '.join(allowed)}",
            )
        try:
            extras[key] = conv(value)
        except ValueError as exc:
            raise _invalid(f"filters.{key}", str(exc)) from exc
    q = filters.get("q")
    if q is not None and len(q) > MAX_Q_LEN:
        raise _invalid("filters.q", f"at most {MAX_Q_LEN} characters")
    lq = ListQuery(
        page=PageParams(),
        order_by=parse_sort(src.spec, filters.get("sort"), src.id_column),
        where=parse_filters(src.spec, {k: v for k, v in filters.items() if k.startswith("filter")}),
    )
    return ParsedFilters(q=q, extras=extras, lq=lq)
