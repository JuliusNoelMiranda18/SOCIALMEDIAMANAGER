from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Campaign, SocialPostEntry


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
    """Acceptance always wins over any concurrent error write (ISSUE-009)."""
    q = (
        update(SocialPostEntry)
        .where(SocialPostEntry.id == entry_id)
        .values(platform_post_id=platform_post_id, status="publishing", last_error=None)
    )
    session.execute(q)


def record_error(session: Session, entry_id: int, error: str | None, status: str) -> None:
    """Write an error outcome, never over an accepted entry (ISSUE-009)."""
    q = (
        update(SocialPostEntry)
        .where(SocialPostEntry.id == entry_id, SocialPostEntry.platform_post_id.is_(None))
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
        )
        .values(status="publishing")
    )
    session.execute(q)
