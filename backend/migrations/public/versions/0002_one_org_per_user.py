"""one organization per user (design B04 D1)

Replaces the B02 unique (user_id, org_id) with unique (user_id): a user can
belong to at most one organization. Platform admins have no membership.

Revision ID: 0002_one_org_per_user
Revises: 0001_public_initial
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_one_org_per_user"
down_revision: str | None = "0001_public_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "public"
NAME = "uq_org_memberships_user_id"  # same name as before (naming convention: column_0)


def upgrade() -> None:
    # Fail with a readable message instead of a bare unique-violation: an
    # operator must decide which membership to keep.
    dupes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT u.email FROM public.org_memberships m "
                "JOIN public.users u ON u.id = m.user_id "
                "GROUP BY u.email HAVING count(*) > 1 ORDER BY 1 LIMIT 20"
            )
        )
        .scalars()
        .all()
    )
    if dupes:
        raise RuntimeError(
            "cannot enforce one organization per user; users with several memberships: "
            + ", ".join(dupes)
        )
    op.drop_constraint(NAME, "org_memberships", schema=S, type_="unique")
    op.create_unique_constraint(NAME, "org_memberships", ["user_id"], schema=S)


def downgrade() -> None:
    op.drop_constraint(NAME, "org_memberships", schema=S, type_="unique")
    op.create_unique_constraint(NAME, "org_memberships", ["user_id", "org_id"], schema=S)
