"""Searchable resource types (design B07 §3.3, D14).

A module makes its rows searchable by adding `search.py` that calls
`register(SearchSource(...))`; the registry imports those files. Search then
needs no edit when a module is added (deliverables reusability rule 1).

`build(q)` returns a SELECT of exactly four labelled columns, matching rows
only (live rows, the module's own idea of "deleted" excluded):
    id (uuid), title (text), snippet (text or NULL), score (float)
Use `match_and_score()` for the standard rule so every type ranks alike.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Float, Select, cast, func, or_

from app.modules import registry

# backend_processes.md §7 says similarity(name, q) > 0.3. Ruling (B07 build):
# word_similarity is used instead, because whole-string similarity of a long
# name against a short query stays under 0.3 even for a one-letter typo
# ("quartrly" vs "quarterly-report.pdf" = 0.30). word_similarity compares q
# with the best-matching part of the title (0.58 there).
FUZZY_THRESHOLD = 0.5
# Code-like queries (invoice numbers, order ids) match exactly: typo matching
# would surface the neighbours (INV-2026-0413 for INV-2026-0412). A query is
# code-like when at least this share of its letters and digits are digits.
# User decision 2026-11-20.
CODE_DIGIT_SHARE = 0.5


def is_code_like(q: str) -> bool:
    """ "INV-2026-0412" -> True (8 of 11); "report 2026" -> False (4 of 10)."""
    alnum = [c for c in q if c.isalnum()]
    return bool(alnum) and sum(c.isdigit() for c in alnum) / len(alnum) >= CODE_DIGIT_SHARE


@dataclass(frozen=True)
class SearchSource:
    type: str  # public name in ?types= and in each hit, e.g. "files"
    permission: str  # read key the caller needs, e.g. "files:read"
    build: Callable[[str], Select]


_sources: dict[str, SearchSource] = {}


def register(src: SearchSource) -> None:
    """Add a source. A second source with the same type fails at import."""
    existing = _sources.get(src.type)
    if existing is not None and existing != src:
        raise ValueError(f"search type {src.type!r} registered twice")
    _sources[src.type] = src


def sources() -> dict[str, SearchSource]:
    """Every registered source, loading the modules' search.py files first."""
    registry.load_parts("search")
    return dict(_sources)


def match_and_score(
    search_vector: Any, title: Any, q: str
) -> tuple[ColumnElement[bool], ColumnElement[Any]]:
    """(WHERE clause, score) for full text on `search_vector` + fuzzy on `title`."""
    tsq = func.plainto_tsquery("simple", q)
    fts = search_vector.op("@@")(tsq)
    if is_code_like(q):
        # Exact only: full text, plus a case-insensitive substring so a code
        # inside a file name ("INV-…-0412.pdf", one parser token) is found too.
        contains = title.ilike(f"%{_escape_like(q.strip())}%", escape="\\")
        score = cast(func.ts_rank(search_vector, tsq) + 1.0, Float)
        return or_(fts, contains), score
    fuzzy = func.word_similarity(q, title)
    where = or_(fts, fuzzy > FUZZY_THRESHOLD)
    score = cast(func.ts_rank(search_vector, tsq) + fuzzy, Float)
    return where, score


def _escape_like(q: str) -> str:
    """Literal substring: user input must not act as LIKE wildcards."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
