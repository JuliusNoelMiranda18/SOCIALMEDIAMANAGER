"""publish state on social_post_entries

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"

T = "social_post_entries"


def upgrade() -> None:
    op.add_column(T, sa.Column("idempotency_key", sa.Text))
    op.add_column(T, sa.Column("attempts", sa.Integer, server_default="0", nullable=False))
    op.add_column(T, sa.Column("last_error", sa.Text))
    op.create_unique_constraint("social_post_entries_idempotency_key_key", T, ["idempotency_key"])


def downgrade() -> None:
    for c in ("last_error", "attempts", "idempotency_key"):
        op.drop_column(T, c)
