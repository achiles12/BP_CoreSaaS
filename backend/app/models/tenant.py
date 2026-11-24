"""Per-tenant schema models: T01–T05, T07 (data_model.md §2, design B02 §3.2, B05 §3.2).

Declared under the placeholder schema "tenant" (see models/base.py). Never
query these through a plain session: use core.tenancy.tenant_session(), which
maps "tenant" to the organization's real schema.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase, created_at, updated_at, uuid_pk
from app.models.public import User


class Role(TenantBase):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # owner, admin, ...
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Lower wins when a user holds several roles (owner=10 ... user=50).
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    landing_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class Permission(TenantBase):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # module:action
    module: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(TenantBase):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(TenantBase):
    __tablename__ = "user_roles"

    # Cross-schema FK to public.users (data_model §3). Built from the Column
    # object because the two tables live in different MetaData collections.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.roles.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assigned_at: Mapped[datetime] = created_at()


class Setting(TenantBase):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# B05: a file row moves pending -> active (confirm) -> deleted (soft delete);
# J04 hard-deletes pending rows older than 24 h and deleted rows (design D12).
FILE_STATUSES = ("pending", "active", "deleted")


class File(TenantBase):
    """T05: metadata of one object in RustFS (the bytes never touch Postgres)."""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(repr(v) for v in FILE_STATUSES) + ")", name="status"
        ),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        # Full-text search (B07) and typo-tolerant name matching (`q`, trigram).
        Index("ix_files_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_files_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "public.gin_trgm_ops"},
        ),
        # Lists are "active files, newest first"; mine=true adds uploaded_by.
        Index("ix_files_status_created_at", "status", text("created_at DESC")),
        Index("ix_files_uploaded_by_created_at", "uploaded_by", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)  # original name, cleaned (D5)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # D8
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), nullable=False
    )
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', name)", persisted=True)
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
