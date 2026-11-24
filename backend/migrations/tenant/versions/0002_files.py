"""tenant files: file metadata for RustFS objects (T05, design B05 §3.3)

Runs with search_path = the tenant schema (see migrations/tenant/env.py), so
the table is created WITHOUT a schema. pg_trgm comes from deploy/postgres/
init.sql (B00) / public migration 0001 and lives in public. The tenant
search_path holds only the tenant schema, so the operator class is named
`public.gin_trgm_ops` explicitly.

Revision ID: 0002_files
Revises: 0001_tenant_initial
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002_files"
down_revision: str | None = "0001_tenant_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("uploaded_by", UUID, nullable=False),
        # Generated, so it can never drift from `name` (data_model.md T05).
        sa.Column(
            "search_vector",
            pg.TSVECTOR,
            sa.Computed("to_tsvector('simple', name)", persisted=True),
        ),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.Column("deleted_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_files"),
        sa.UniqueConstraint("object_key", name="uq_files_object_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'deleted')", name=op.f("ck_files_status")
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_files_size_bytes_positive")),
        # Cross-schema FK (data_model §3): users are never hard-deleted.
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["public.users.id"],
            ondelete="RESTRICT",
            name="fk_files_uploaded_by_users",
        ),
    )
    op.create_index("ix_files_search_vector", "files", ["search_vector"], postgresql_using="gin")
    op.create_index(
        "ix_files_name_trgm",
        "files",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "public.gin_trgm_ops"},
    )
    op.create_index("ix_files_status_created_at", "files", ["status", sa.text("created_at DESC")])
    op.create_index(
        "ix_files_uploaded_by_created_at", "files", ["uploaded_by", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_table("files")  # drops its indexes and constraints with it
