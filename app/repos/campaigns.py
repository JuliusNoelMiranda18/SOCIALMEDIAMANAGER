from sqlalchemy import case, exists, select, text, update
from sqlalchemy.orm import Session, selectinload

from app.models import Campaign, SocialPostEntry, WebhookEvent

# State machine: draft -> queued -> publishing -> published | failed. 'published' is final:
# every write below excludes it. 'failed' is left only by an explicit publish (Stage 3 retry).
NOT_PUBLISHED = SocialPostEntry.status != "published"
PLATFORM_FAILURE = "platform reported failure"


def add(session: Session, post_id: int, brand_name: str | None) -> Campaign:
    campaign = Campaign(post_id=post_id, brand_name=brand_name)
    session.add(campaign)
    session.flush()
    return campaign


def add_entry(session: Session, **fields) -> SocialPostEntry:
    entry = SocialPostEntry(**fields)
    session.add(entry)
    session.flush()
    return entry


def get(session: Session, campaign_id: int) -> Campaign | None:
    q = select(Campaign).where(Campaign.id == campaign_id).options(selectinload(Campaign.entries))
    return session.scalars(q).one_or_none()


def mark_queued(session: Session, campaign_id: int) -> None:
    """Enqueueing a publish: draft -> queued (only draft; caller commits with the job insert)."""
    q = (
        update(SocialPostEntry)
        .where(SocialPostEntry.campaign_id == campaign_id, SocialPostEntry.status == "draft")
        .values(status="queued")
    )
    session.execute(q)


def take_attempt(session: Session, entry_id: int, max_attempts: int) -> int | None:
    """Atomically count one attempt; None once the cap is reached (ISSUE-008) or the entry
    was accepted by a concurrent publish (ISSUE-009)."""
    q = (
        update(SocialPostEntry)
        .where(
            SocialPostEntry.id == entry_id,
            SocialPostEntry.attempts < max_attempts,
            SocialPostEntry.platform_post_id.is_(None),
        )
        .values(attempts=SocialPostEntry.attempts + 1)
        .returning(SocialPostEntry.attempts)
    )
    return session.execute(q).scalar_one_or_none()


def mark_accepted(session: Session, entry_id: int, platform_post_id: str) -> None:
    """Acceptance always wins over any concurrent error write (ISSUE-009). A verified callback
    stored before we got here (it can beat the 201 back) decides the final status at once."""

    def stored(status: str):
        return exists().where(
            WebhookEvent.platform_post_id == platform_post_id, WebhookEvent.status == status
        )

    # ISSUE-010: serialize with the webhook per post id; held until the caller commits
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": platform_post_id})
    q = (
        update(SocialPostEntry)
        .where(SocialPostEntry.id == entry_id, NOT_PUBLISHED)
        .values(
            platform_post_id=platform_post_id,
            status=case(
                (stored("delivered"), "published"),
                (stored("failed"), "failed"),
                else_="publishing",
            ),
            last_error=case((stored("failed"), PLATFORM_FAILURE), else_=None),
        )
    )
    session.execute(q)


def apply_delivery(session: Session, platform_post_id: str, status: str) -> bool:
    """Webhook outcome: only a 'publishing' entry moves. True if a row changed."""
    values = {"status": "published"}
    if status == "failed":
        values = {"status": "failed", "last_error": PLATFORM_FAILURE}
    q = (
        update(SocialPostEntry)
        .where(
            SocialPostEntry.platform_post_id == platform_post_id,
            SocialPostEntry.status == "publishing",
        )
        .values(**values)
    )
    return session.execute(q).rowcount > 0


def record_error(session: Session, entry_id: int, error: str | None, status: str) -> None:
    """Write an error outcome, never over an accepted entry (ISSUE-009)."""
    q = (
        update(SocialPostEntry)
        .where(
            SocialPostEntry.id == entry_id,
            SocialPostEntry.platform_post_id.is_(None),
            NOT_PUBLISHED,
        )
        .values(status=status, last_error=error)
    )
    if status != "failed":  # a late retryable error never revives a concurrently failed entry
        q = q.where(SocialPostEntry.status != "failed")
    session.execute(q)


def mark_publishing(session: Session, entry_id: int, max_attempts: int) -> None:
    """Never resets a capped or accepted entry: a late write cannot undo a concurrent 'failed'."""
    q = (
        update(SocialPostEntry)
        .where(
            SocialPostEntry.id == entry_id,
            SocialPostEntry.attempts < max_attempts,
            SocialPostEntry.platform_post_id.is_(None),
            NOT_PUBLISHED,
        )
        .values(status="publishing")
    )
    session.execute(q)
