"""Request/response models of the template module (design B06 D10)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_TITLE_LEN = 200
MAX_DESCRIPTION_LEN = 5000

ItemStatus = Literal["open", "in_progress", "done"]  # models.ITEM_STATUSES


def _clean_title(v: str) -> str:
    v = " ".join(v.split())  # trim + collapse inner whitespace
    if not v:
        raise ValueError("must not be empty")
    return v


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are a client bug: 422

    title: str = Field(min_length=1, max_length=MAX_TITLE_LEN)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)
    status: ItemStatus = "open"

    _title = field_validator("title")(_clean_title)


class ItemUpdate(BaseModel):
    """PATCH body: only the fields sent are changed; at least one is required."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LEN)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)
    status: ItemStatus | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return None if v is None else _clean_title(v)

    @model_validator(mode="after")
    def _not_empty(self) -> "ItemUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one of title, description, status")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        return self


class ItemOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    owner_id: uuid.UUID
    owner_name: str | None  # public.users.full_name
    created_at: datetime
    updated_at: datetime
