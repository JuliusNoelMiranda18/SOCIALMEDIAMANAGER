import io
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.content.captions import summarize
from app.content.images import SIZES, render
from app.content.llm import generate_caption
from app.models import Campaign
from app.repos import campaigns as repo
from app.repos import posts as posts_repo
from app.services.errors import NotFound


def create_campaign(
    session: Session, post_id: int, platforms: list[str], brand_name: str | None
) -> Campaign:
    """Generate images and captions for every platform in one transaction; all or nothing."""
    post = posts_repo.get(session, post_id)
    if post is None:
        raise NotFound("post not found")
    source = Image.open(io.BytesIO(post.source_image)) if post.source_image else None
    summary = summarize(post.body)
    media = Path(settings.media_dir)
    media.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        campaign = repo.add(session, post_id, brand_name)
        for platform in platforms:
            name = f"{campaign.id}_{platform}.png"
            w, h = SIZES[platform]
            entry = repo.add_entry(
                session,
                campaign_id=campaign.id,
                platform=platform,
                caption="",
                image_path=name,
                image_width=w,
                image_height=h,
            )
            entry.caption = generate_caption(
                platform, summary, entry.id, session, title=post.title, url=post.source_url
            )
            written.append(media / name)
            render(platform, source, post.title, brand_name).save(media / name, "PNG")
        session.commit()
    except BaseException:
        session.rollback()
        for f in written:
            f.unlink(missing_ok=True)
        raise
    return repo.get(session, campaign.id)


def get_campaign(session: Session, campaign_id: int) -> Campaign:
    campaign = repo.get(session, campaign_id)
    if campaign is None:
        raise NotFound("campaign not found")
    return campaign
