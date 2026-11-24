"""Request/response models of the exports module (api_spec.md §8, design B07 §3.4)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExportFormat = Literal["csv", "xlsx"]  # models.EXPORT_FORMATS
MAX_FILTER_KEYS = 30


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str = Field(min_length=1, max_length=50, description="files, items or users")
    format: ExportFormat = "csv"
    # The list's query parameters, e.g. {"q": "plan", "filter[status]": "open"}.
    filters: dict[str, str] = Field(default_factory=dict, max_length=MAX_FILTER_KEYS)


class ExportOut(BaseModel):
    id: uuid.UUID
    resource: str
    format: str
    filters: dict[str, str]
    status: str  # queued | running | done | failed | expired
    row_count: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None  # when the file will be removed (done only; None = kept)
    download_url: str | None  # GET /exports/{id} only, while done (D9)
    download_expires_in: int | None
