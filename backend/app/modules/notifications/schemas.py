"""Response models of the notifications module (design B07 §3.7)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    body: str | None
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class ReadAllOut(BaseModel):
    updated: int  # how many notifications were unread and are now read
