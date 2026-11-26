"""jobs.last_error + one active publish job per campaign

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.add_column("jobs", sa.Column("last_error", sa.Text))
    op.create_index(
        "uq_jobs_active_campaign",
        "jobs",
        [sa.text("(payload->>'campaign_id')")],
        unique=True,
        postgresql_where=sa.text("kind = 'publish_campaign' AND status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_active_campaign", "jobs")
    op.drop_column("jobs", "last_error")
