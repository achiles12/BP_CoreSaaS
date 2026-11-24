"""Tenant table of the template module: `_template_items` (T09, design B06 D10).

A module keeps its own tables here (B06 D4); app/modules/registry.py imports
this file so TenantBase.metadata (drift test, tooling) sees the table. The
real table is created by tenant migration 0003_items.

COPYING: rename the class, __tablename__, index names and constraint names.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase, created_at, updated_at, uuid_pk
from app.models.public import User

ITEM_STATUSES = ("open", "in_progress", "done")


class TemplateItem(TenantBase):
    __tablename__ = "_template_items"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(repr(v) for v in ITEM_STATUSES) + ")", name="status"
        ),
        # Full-text (B07 search) and trigram (`q` contains) indexes, as for files.
        Index("ix__template_items_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix__template_items_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "public.gin_trgm_ops"},
        ),
        Index("ix__template_items_status_created_at", "status", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    # The creator (D10); read-only after create. Users are never hard-deleted.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', title || ' ' || coalesce(description, ''))", persisted=True
        ),
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
