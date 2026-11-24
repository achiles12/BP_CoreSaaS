"""Tenant table of the notifications module: `notifications` (T06, design B07 §3.1).

Kept in the module (B06 D4); created by tenant migration 0004. A row belongs
to one user; `read_at` stays NULL until the user marks it read.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase, created_at, uuid_pk
from app.models.public import User


class Notification(TenantBase):
    __tablename__ = "notifications"
    __table_args__ = (
        # "my unread, newest first" (data_model.md T06)
        Index("ix_notifications_user_read_created", "user_id", "read_at", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # A user's notifications go with the user (users are never hard-deleted today).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "export.done"
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # Free-form payload for the UI, e.g. {"export_id": ..., "resource": "items"}.
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
