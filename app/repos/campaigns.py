from sqlalchemy import select
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
