"""Durable jobs: enqueue a campaign publish now or later; the worker runs it (app/worker)."""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Job
from app.repos import jobs as repo
from app.services.campaigns import get_campaign
from app.services.errors import Conflict, NotFound

PUBLISH = "publish_campaign"


def schedule_campaign(session: Session, campaign_id: int, run_at: datetime | None) -> Job:
    """run_at is naive UTC (None = now). One active job per campaign, enforced by the DB."""
    get_campaign(session, campaign_id)
    try:
        job = repo.enqueue(session, PUBLISH, {"campaign_id": campaign_id}, run_at)
        session.commit()
    except IntegrityError as e:
        session.rollback()
        raise Conflict("campaign already has an active publish job") from e
    session.refresh(job)  # load server defaults (run_at, status, attempts)
    return job


def publish_now(session: Session, campaign_id: int) -> Job:
    return schedule_campaign(session, campaign_id, None)


def get_job(session: Session, job_id: int) -> Job:
    job = repo.get(session, job_id)
    if job is None:
        raise NotFound("job not found")
    return job


def advance_time(session: Session, seconds: int) -> int:
    shifted = repo.advance(session, seconds)
    session.commit()
    return shifted
