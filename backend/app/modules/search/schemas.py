"""Response model of GET /search (api_spec.md §7, design B07 D10)."""

import uuid

from pydantic import BaseModel


class SearchHit(BaseModel):
    type: str  # "files", "items", ...
    id: uuid.UUID
    title: str
    snippet: str | None  # plain text, no markup (D11); null when the type has no body
    score: float
