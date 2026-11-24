"""Organization request/response models (design B04 §3.6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_ORG_NAME = 200


class OrgListItem(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    status: str


class OrgOut(BaseModel):
    id: uuid.UUID
    slug: str  # read-only (X-Tenant value)
    name: str
    display_name: str | None  # tenant setting app.display_name
    status: str
    plan: str
    created_at: datetime


class OrgUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_ORG_NAME)
    display_name: str | None = Field(default=None, max_length=MAX_ORG_NAME)

    @field_validator("name", "display_name")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if not v:
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def _something(self) -> "OrgUpdateIn":
        if self.name is None and self.display_name is None:
            raise ValueError("nothing to update: send name and/or display_name")
        return self
