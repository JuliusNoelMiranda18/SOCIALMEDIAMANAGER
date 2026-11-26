"""The only publishing surface services may import: the protocol, its types, and the factory."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class PublishRequest:
    platform: str
    caption: str
    image_url: str | None
    idempotency_key: str


@dataclass(frozen=True)
class PublishOutcome:
    kind: Literal["accepted", "rate_limited", "retryable", "fatal"]
    platform_post_id: str | None = None
    wait_seconds: float | None = None  # rate_limited only
    reason: str = ""


class SocialPublisher(Protocol):
    def publish(self, req: PublishRequest) -> PublishOutcome: ...


def get_publisher(platform: str) -> SocialPublisher:
    from app.publishers import fake  # lazy: keeps adapters out of the protocol's import graph

    return {"instagram": fake.FakeInstagramPublisher, "x": fake.FakeXPublisher}[platform]()
