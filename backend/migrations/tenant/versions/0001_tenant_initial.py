"""tenant initial: roles, permissions, role_permissions, user_roles, settings (T01–T04, T07)

Runs with search_path = the tenant schema (see migrations/tenant/env.py), so
tables are created WITHOUT a schema. References to shared tables are explicit
(public.users).

Revision ID: 0001_tenant_initial
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_tenant_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", UUID, server_default=GEN_UUID),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("landing_path", sa.Text, nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("key", name="uq_roles_key"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", UUID, server_default=GEN_UUID),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("module", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("key", name="uq_permissions_key"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID, nullable=False),
        sa.Column("permission_id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="CASCADE", name="fk_role_permissions_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            ondelete="CASCADE",
            name="fk_role_permissions_permission_id_permissions",
        ),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role_id", UUID, nullable=False),
        sa.Column("assigned_by", UUID),
        sa.Column("assigned_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        # Cross-schema FK (data_model §3): users are never hard-deleted.
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id"],
            ondelete="RESTRICT",
            name="fk_user_roles_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="CASCADE", name="fk_user_roles_role_id_roles"
        ),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("value", pg.JSONB, nullable=False),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_by", UUID),
        sa.PrimaryKeyConstraint("key", name="pk_settings"),
    )


def downgrade() -> None:
    for table in ("settings", "user_roles", "role_permissions", "permissions", "roles"):
        op.drop_table(table)
