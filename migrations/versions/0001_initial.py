"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None

NOW = sa.text("now()")


def _id():
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _created(name="created_at"):
    return sa.Column(name, sa.DateTime, server_default=NOW, nullable=False)


def upgrade() -> None:
    op.create_table(
        "posts",
        _id(),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("source_image", sa.LargeBinary),
        _created(),
    )
    op.create_table(
        "campaigns",
        _id(),
        sa.Column("post_id", sa.BigInteger, sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("brand_name", sa.String(60)),
        _created(),
    )
    op.create_index("ix_campaigns_post_id", "campaigns", ["post_id"])
    op.create_table(
        "social_post_entries",
        _id(),
        sa.Column("campaign_id", sa.BigInteger, sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("caption", sa.Text, nullable=False),
        sa.Column("image_path", sa.Text, nullable=False),
        sa.Column("image_width", sa.Integer, nullable=False),
        sa.Column("image_height", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("platform_post_id", sa.Text),
        _created(),
        sa.UniqueConstraint("campaign_id", "platform"),
    )
    op.create_table(
        "platform_tokens",
        _id(),
        sa.Column("platform", sa.String(20), nullable=False, unique=True),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        _created(),
    )
    op.create_table(
        "jobs",
        _id(),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("run_at", sa.DateTime, server_default=NOW, nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime),
        _created(),
    )
    op.create_index("ix_jobs_status_run_at", "jobs", ["status", "run_at"])
    op.create_table(
        "webhook_events",
        _id(),
        sa.Column("event_id", sa.String(200), nullable=False, unique=True),
        sa.Column("raw_body", sa.Text, nullable=False),
        sa.Column("signature_valid", sa.Boolean, nullable=False),
        _created("received_at"),
    )
    op.create_table(
        "llm_calls",
        _id(),
        sa.Column("entry_id", sa.BigInteger, sa.ForeignKey("social_post_entries.id")),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False),
        sa.Column("completion_tokens", sa.Integer, nullable=False),
        sa.Column("cost_micro_usd", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _created(),
    )
    op.create_index("ix_llm_calls_entry_id", "llm_calls", ["entry_id"])


def downgrade() -> None:
    for t in (
        "llm_calls",
        "webhook_events",
        "jobs",
        "platform_tokens",
        "social_post_entries",
        "campaigns",
        "posts",
    ):
        op.drop_table(t)
