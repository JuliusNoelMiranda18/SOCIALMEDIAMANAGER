"""Publish a campaign's entries (ADR-002). Owns the retry policy; adapters make one attempt each."""

import hashlib
import random
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Campaign, SocialPostEntry
from app.publishers import PublishRequest, get_publisher
from app.repos import campaigns as repo
from app.services.campaigns import get_campaign


def backoff_seconds(attempt: int) -> float:
    """Full jitter: uniform(0, min(cap, base * 2**(attempt-1)))."""
    ceiling = min(settings.backoff_cap_ms, settings.backoff_base_ms * 2 ** (attempt - 1))
    return random.uniform(0, ceiling) / 1000


def publish_campaign(
    session: Session, campaign_id: int, *, sleep: Callable[[float], None] = time.sleep
) -> Campaign:
    campaign = get_campaign(session, campaign_id)
    for entry in campaign.entries:
        # Already accepted or published: a no-op, so publishing twice is safe.
        if entry.status == "published" or entry.platform_post_id:
            continue
        try:
            _publish_entry(session, campaign, entry, sleep)
        except Exception as e:  # last resort: one bad entry never 500s the whole publish
            session.rollback()
            # type only: no secrets
            repo.record_error(session, entry.id, type(e).__name__, "failed")
            session.commit()
        session.refresh(entry)  # outcomes are written in SQL, not through the ORM
    return repo.get(session, campaign_id)


def _publish_entry(
    session: Session, campaign: Campaign, entry: SocialPostEntry, sleep: Callable[[float], None]
) -> None:
    if entry.attempts >= settings.publish_max_attempts:
        # the cap is per entry, across publishes; keep last_error
        repo.record_error(session, entry.id, entry.last_error, "failed")
        session.commit()
        return
    if entry.idempotency_key is None:
        raw = f"{campaign.id}:{campaign.post_id}:{entry.platform}"
        entry.idempotency_key = hashlib.sha256(raw.encode()).hexdigest()
    repo.mark_publishing(session, entry.id, settings.publish_max_attempts)
    session.commit()  # the key is durable before any network call
    req = PublishRequest(
        platform=entry.platform,
        caption=entry.caption,
        image_url=f"{settings.public_base_url}/media/{entry.image_path}",
        idempotency_key=entry.idempotency_key,
    )
    publisher = get_publisher(entry.platform)
    max_attempts = settings.publish_max_attempts
    # Outcomes go through conditional SQL so an accepted entry is never marked failed (ISSUE-009).
    while True:
        attempt = repo.take_attempt(session, entry.id, max_attempts)
        session.commit()  # the count is durable (and the row lock released) before the call
        if attempt is None:
            break  # cap reached or accepted by a concurrent publish, which sets the final status
        out = publisher.publish(req)
        if out.kind == "accepted":
            repo.mark_accepted(session, entry.id, out.platform_post_id)
            break  # stays 'publishing' until a verified webhook (Stage 5)
        error, status = out.reason, "publishing"
        if out.kind == "fatal" or attempt == max_attempts:
            status = "failed"
        elif out.kind == "rate_limited" and out.wait_seconds > settings.max_retry_after_seconds:
            status = "failed"
            error = (
                f"Retry-After {out.wait_seconds:.0f}s exceeds "
                f"MAX_RETRY_AFTER_SECONDS={settings.max_retry_after_seconds}"
            )
        repo.record_error(session, entry.id, error, status)
        session.commit()
        if status == "failed":
            break
        wait = backoff_seconds(attempt)
        if out.kind == "rate_limited":
            wait = max(out.wait_seconds, wait)
        sleep(wait)
    session.commit()
