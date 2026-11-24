"""public initial: users, organizations, memberships, tokens, invitations (E01–E06)

Revision ID: 0001_public_initial
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_public_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "public"
UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    # Normally created by deploy/postgres/init.sql; repeated here so a bare
    # database (tests, a new server) migrates on its own. citext is a trusted
    # extension (PG13+), so the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "users",
        _id(),
        sa.Column("email", pg.CITEXT, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("full_name", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_platform_admin", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema=S,
    )

    op.create_table(
        "organizations",
        _id(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", pg.CITEXT, nullable=False),
        sa.Column("schema_name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'provisioning'")),
        sa.Column("plan", sa.Text, nullable=False, server_default=sa.text("'free'")),
        sa.Column("limits", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        sa.UniqueConstraint("schema_name", name="uq_organizations_schema_name"),
        sa.CheckConstraint(
            "slug ~ '^[a-z][a-z0-9_]{2,30}$'", name=op.f("ck_organizations_slug_format")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'provisioning', 'failed')",
            name=op.f("ck_organizations_status"),
        ),
        schema=S,
    )

    op.create_table(
        "org_memberships",
        _id(),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("org_id", UUID, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_org_memberships"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id"],
            ondelete="RESTRICT",
            name="fk_org_memberships_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["public.organizations.id"],
            ondelete="RESTRICT",
            name="fk_org_memberships_org_id_organizations",
        ),
        sa.UniqueConstraint("user_id", "org_id", name="uq_org_memberships_user_id"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name=op.f("ck_org_memberships_status")
        ),
        schema=S,
    )
    op.create_index("ix_public_org_memberships_org_id", "org_memberships", ["org_id"], schema=S)

    op.create_table(
        "refresh_tokens",
        _id(),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("family_id", UUID, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.Column("replaced_by", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("ip", pg.INET),
        sa.Column("user_agent", sa.Text),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id"],
            ondelete="RESTRICT",
            name="fk_refresh_tokens_user_id_users",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        schema=S,
    )
    op.create_index("ix_public_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema=S)
    op.create_index("ix_public_refresh_tokens_family_id", "refresh_tokens", ["family_id"], schema=S)

    op.create_table(
        "invitations",
        _id(),
        sa.Column("org_id", UUID, nullable=False),
        sa.Column("email", pg.CITEXT, nullable=False),
        sa.Column("role_key", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("invited_by", UUID),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("accepted_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["public.organizations.id"],
            ondelete="RESTRICT",
            name="fk_invitations_org_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["public.users.id"],
            ondelete="RESTRICT",
            name="fk_invitations_invited_by_users",
        ),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        schema=S,
    )
    op.create_index(
        "uq_invitations_open_org_email",
        "invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
        schema=S,
    )

    for table in ("email_verification_tokens", "password_reset_tokens"):
        op.create_table(
            table,
            _id(),
            sa.Column("token_hash", sa.Text, nullable=False),
            sa.Column("expires_at", TS, nullable=False),
            sa.Column("used_at", TS),
            sa.Column("created_at", TS, nullable=False, server_default=NOW),
            sa.Column("user_id", UUID, nullable=False),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["public.users.id"],
                ondelete="RESTRICT",
                name=f"fk_{table}_user_id_users",
            ),
            sa.UniqueConstraint("token_hash", name=f"uq_{table}_token_hash"),
            schema=S,
        )
        op.create_index(f"ix_public_{table}_user_id", table, ["user_id"], schema=S)


def downgrade() -> None:
    for table in (
        "password_reset_tokens",
        "email_verification_tokens",
        "invitations",
        "refresh_tokens",
        "org_memberships",
        "organizations",
        "users",
    ):
        op.drop_table(table, schema=S)
    # Extensions are left in place: other objects (tenant schemas) may use them.
