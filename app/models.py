from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NOW = func.now()


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_image: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    brand_name: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
    entries: Mapped[list["SocialPostEntry"]] = relationship(order_by="SocialPostEntry.id")


class SocialPostEntry(Base):
    __tablename__ = "social_post_entries"
    __table_args__ = (UniqueConstraint("campaign_id", "platform"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    platform: Mapped[str] = mapped_column(String(20))
    caption: Mapped[str] = mapped_column(Text)
    image_path: Mapped[str] = mapped_column(Text)
    image_width: Mapped[int]
    image_height: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    platform_post_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)

    @property
    def image_url(self) -> str:
        return f"/media/{self.image_path}"


class PlatformToken(Base):
    __tablename__ = "platform_tokens"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), unique=True)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Job(Base):
    __tablename__ = "jobs"
    # The worker claims by (status, run_at); one active publish job per campaign (0003).
    __table_args__ = (
        Index("ix_jobs_status_run_at", "status", "run_at"),
        Index(
            "uq_jobs_active_campaign",
            text("(payload->>'campaign_id')"),
            unique=True,
            postgresql_where=text("kind = 'publish_campaign' AND status IN ('pending', 'running')"),
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    run_at: Mapped[datetime] = mapped_column(server_default=NOW)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    attempts: Mapped[int] = mapped_column(server_default="0")
    locked_until: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)

    @property
    def campaign_id(self) -> int | None:
        return self.payload.get("campaign_id")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), unique=True)
    raw_body: Mapped[str] = mapped_column(Text)
    signature_valid: Mapped[bool]
    received_at: Mapped[datetime] = mapped_column(server_default=NOW)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("social_post_entries.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    cost_micro_usd: Mapped[int]
    latency_ms: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
