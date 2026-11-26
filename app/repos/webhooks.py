from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import WebhookEvent


def store(
    session: Session, event_id: str, raw_body: str, platform_post_id: str, status: str
) -> bool:
    """Insert a verified event; False if event_id was already stored (the unique constraint)."""
    # ISSUE-010: serialize with mark_accepted per post id; held until this transaction ends
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": platform_post_id})
    q = (
        insert(WebhookEvent)
        .values(
            event_id=event_id,
            raw_body=raw_body,
            signature_valid=True,
            platform_post_id=platform_post_id,
            status=status,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(WebhookEvent.id)
    )
    return session.execute(q).scalar_one_or_none() is not None
