from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.api.schemas import CampaignIn, CampaignOut, PgId, PostIn, PostOut
from app.db import get_session
from app.services import campaigns, posts
from app.services.errors import InvalidInput, NotFound

router = APIRouter()
Db = Annotated[Session, Depends(get_session)]


@router.post("/posts", status_code=201, response_model=PostOut)
def create_post(data: PostIn, session: Db):
    try:
        return posts.create_post(session, data.title, data.body, data.source_url, data.image_b64)
    except InvalidInput as e:
        raise HTTPException(422, str(e)) from e


@router.post("/campaigns", status_code=201, response_model=CampaignOut)
def create_campaign(data: CampaignIn, session: Db):
    try:
        return campaigns.create_campaign(session, data.post_id, data.platforms, data.brand_name)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: Annotated[PgId, Path()], session: Db):
    try:
        return campaigns.get_campaign(session, campaign_id)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e
