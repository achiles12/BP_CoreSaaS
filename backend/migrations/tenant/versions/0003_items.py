"""tenant items: the template module's table `_template_items` (T09, design B06 §3.4)

A copied module adds its own revision after the latest one, the same way
(down_revision = the current head). Runs with search_path = the tenant schema.

Revision ID: 0003_items
Revises: 0002_files
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003_items"
down_revision: str | None = "0002_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
T = "_template_items"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'open'")),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column(
            "search_vector",
            pg.TSVECTOR,
            sa.Computed(
                "to_tsvector('simple', title || ' ' || coalesce(description, ''))",
                persisted=True,
            ),
        ),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.Column("deleted_at", TS),
        sa.PrimaryKeyConstraint("id", name=f"pk_{T}"),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'done')", name=op.f(f"ck_{T}_status")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["public.users.id"], ondelete="RESTRICT", name=f"fk_{T}_owner_id_users"
        ),
    )
    op.create_index(f"ix_{T}_search_vector", T, ["search_vector"], postgresql_using="gin")
    op.create_index(
        f"ix_{T}_title_trgm",
        T,
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "public.gin_trgm_ops"},
    )
    op.create_index(f"ix_{T}_status_created_at", T, ["status", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table(T)
