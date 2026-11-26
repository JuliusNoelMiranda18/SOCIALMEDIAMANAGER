"""webhook_events.platform_post_id + status (the table itself exists since 0001)

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.add_column("webhook_events", sa.Column("platform_post_id", sa.Text))
    op.add_column("webhook_events", sa.Column("status", sa.Text))
    # mark_accepted looks up stored events by post id (early-callback race)
    op.create_index("ix_webhook_events_platform_post_id", "webhook_events", ["platform_post_id"])
    # the webhook applies its event by post id
    op.create_index(
        "ix_social_post_entries_platform_post_id", "social_post_entries", ["platform_post_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_social_post_entries_platform_post_id", "social_post_entries")
    op.drop_index("ix_webhook_events_platform_post_id", "webhook_events")
    op.drop_column("webhook_events", "status")
    op.drop_column("webhook_events", "platform_post_id")
