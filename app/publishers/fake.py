"""Adapters for the fake platform. One HTTP attempt per publish(); the service owns retries."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.config import settings
from app.publishers import PublishOutcome, PublishRequest
from app.publishers.tokens import BadTokenResponse, get_token

_client: httpx.Client | None = None


def _default_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            base_url=settings.fake_platform_url, timeout=settings.publish_timeout_seconds
        )
    return _client


def retry_after_seconds(value: str | None) -> float | None:
    """Retry-After as integer seconds or HTTP-date; None if missing or unparseable."""
    v = (value or "").strip()
    if v.isdigit():
        return float(v)
    try:
        when = parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _send(client: httpx.Client, req: PublishRequest) -> PublishOutcome:
    body = {"platform": req.platform, "caption": req.caption, "image_url": req.image_url}

    def post(token: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": req.idempotency_key}
        return client.post("/v1/posts", json=body, headers=headers)

    try:
        r = post(get_token(client, req.platform))
        if r.status_code == 401:
            r = post(get_token(client, req.platform, refresh=True))
    except httpx.HTTPError as e:  # timeout, connection error, token endpoint failure
        return PublishOutcome("retryable", reason=type(e).__name__)
    except BadTokenResponse:
        return PublishOutcome("retryable", reason="bad token response")
    if r.is_success:
        try:
            post_id = r.json()["id"]
        except (ValueError, KeyError, TypeError):
            post_id = None
        if not isinstance(post_id, str) or not post_id:
            # same key on retry, so a replay is safe if the platform did accept it
            return PublishOutcome("retryable", reason="malformed response")
        return PublishOutcome("accepted", platform_post_id=post_id)
    if r.status_code == 429:
        wait = retry_after_seconds(r.headers.get("Retry-After"))
        if wait is None:
            return PublishOutcome("retryable", reason="HTTP 429 without valid Retry-After")
        return PublishOutcome("rate_limited", wait_seconds=wait, reason="HTTP 429")
    if r.status_code >= 500:
        return PublishOutcome("retryable", reason=f"HTTP {r.status_code}")
    return PublishOutcome("fatal", reason=f"HTTP {r.status_code}")


class FakeInstagramPublisher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or _default_client()

    def publish(self, req: PublishRequest) -> PublishOutcome:
        if not req.image_url:
            return PublishOutcome("fatal", reason="instagram requires an image")
        return _send(self._client, req)


class FakeXPublisher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or _default_client()

    def publish(self, req: PublishRequest) -> PublishOutcome:
        if len(req.caption) > 280:
            return PublishOutcome("fatal", reason="x caption over 280 characters")
        return _send(self._client, req)
