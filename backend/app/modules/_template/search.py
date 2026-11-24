"""Items in global search (design B07 §3.3). COPYING: rename type/permission/model.

Snippet: a plain-text extract of the description around the match (D11, no
markup: StartSel/StopSel are empty), NULL when there is no description.
"""

from sqlalchemy import Select, func, select

from app.modules._template.models import TemplateItem
from app.modules.search.sources import SearchSource, match_and_score, register

HEADLINE_OPTIONS = 'StartSel="", StopSel="", MaxWords=20, MinWords=8, ShortWord=2'


def _build(q: str) -> Select:
    where, score = match_and_score(TemplateItem.search_vector, TemplateItem.title, q)
    snippet = func.ts_headline(
        "simple", TemplateItem.description, func.plainto_tsquery("simple", q), HEADLINE_OPTIONS
    )
    return select(
        TemplateItem.id.label("id"),
        TemplateItem.title.label("title"),
        snippet.label("snippet"),
        score.label("score"),
    ).where(TemplateItem.deleted_at.is_(None), where)


register(SearchSource(type="items", permission="items:read", build=_build))
