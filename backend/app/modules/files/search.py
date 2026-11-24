"""Files in global search (design B07 §3.3): active files by name; no snippet."""

from sqlalchemy import Select, Text, null, select

from app.models.tenant import File
from app.modules.search.sources import SearchSource, match_and_score, register


def _build(q: str) -> Select:
    where, score = match_and_score(File.search_vector, File.name, q)
    return select(
        File.id.label("id"),
        File.name.label("title"),
        null().cast(Text).label("snippet"),
        score.label("score"),
    ).where(File.status == "active", where)


register(SearchSource(type="files", permission="files:read", build=_build))
