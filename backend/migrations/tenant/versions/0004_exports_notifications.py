"""tenant exports + notifications: `export_jobs` (T08), `notifications` (T06), design B07 §3.1

Runs with search_path = the tenant schema; public.users is named explicitly.

Revision ID: 0004_exports_notifications
Revises: 0003_items
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004_exports_notifications"
down_revision: str | None = "0003_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
EMPTY_JSON = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("data", pg.JSONB, nullable=False, server_default=EMPTY_JSON),
        sa.Column("read_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id"],
            ondelete="CASCADE",
            name="fk_notifications_user_id_users",
        ),
    )
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "read_at", sa.text("created_at DESC")],
    )

    op.create_table(
        "export_jobs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()")),
        sa.Column("requested_by", UUID, nullable=False),
        sa.Column("resource", sa.Text, nullable=False),
        sa.Column("format", sa.Text, nullable=False),
        sa.Column("filters", pg.JSONB, nullable=False, server_default=EMPTY_JSON),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("object_key", sa.Text),
        sa.Column("row_count", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("finished_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_export_jobs"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'expired')",
            name=op.f("ck_export_jobs_status"),
        ),
        sa.CheckConstraint("format IN ('csv', 'xlsx')", name=op.f("ck_export_jobs_format")),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["public.users.id"],
            ondelete="RESTRICT",
            name="fk_export_jobs_requested_by_users",
        ),
    )
    op.create_index(
        "ix_export_jobs_requested_by_created_at",
        "export_jobs",
        ["requested_by", sa.text("created_at DESC")],
    )
    op.create_index("ix_export_jobs_status_finished_at", "export_jobs", ["status", "finished_at"])


def downgrade() -> None:
    op.drop_table("export_jobs")
    op.drop_table("notifications")
