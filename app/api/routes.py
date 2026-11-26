from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.api.schemas import (
    AdvanceTimeIn,
    CampaignIn,
    CampaignOut,
    JobOut,
    PgId,
    PostIn,
    PostOut,
    ScheduleIn,
)
from app.db import get_session
from app.services import campaigns, jobs, posts
from app.services.errors import Conflict, InvalidInput, NotFound

router = APIRouter()
dev_router = APIRouter()  # included by app.main only when DEV_ENDPOINTS=true
Db = Annotated[Session, Depends(get_session)]
CampaignId = Annotated[PgId, Path()]


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
def get_campaign(campaign_id: CampaignId, session: Db):
    try:
        return campaigns.get_campaign(session, campaign_id)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e


def _enqueue(session: Session, campaign_id: int, run_at):
    try:
        return jobs.schedule_campaign(session, campaign_id, run_at)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e
    except Conflict as e:
        raise HTTPException(409, str(e)) from e


@router.post("/campaigns/{campaign_id}/publish", status_code=202, response_model=JobOut)
def publish_campaign(campaign_id: CampaignId, session: Db):
    return _enqueue(session, campaign_id, None)  # due now; the worker publishes it


@router.post("/campaigns/{campaign_id}/schedule", status_code=202, response_model=JobOut)
def schedule_campaign(campaign_id: CampaignId, data: ScheduleIn, session: Db):
    return _enqueue(session, campaign_id, data.run_at)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: Annotated[PgId, Path()], session: Db):
    try:
        return jobs.get_job(session, job_id)
    except NotFound as e:
        raise HTTPException(404, str(e)) from e


@dev_router.post("/_dev/advance-time")
def advance_time(data: AdvanceTimeIn, session: Db) -> dict[str, int]:
    return {"shifted": jobs.advance_time(session, data.seconds)}
