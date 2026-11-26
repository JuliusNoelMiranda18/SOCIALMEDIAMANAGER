from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Job

NOW = func.now()


def enqueue(session: Session, kind: str, payload: dict, run_at: datetime | None) -> Job:
    """IntegrityError if the campaign already has an active job (uq_jobs_active_campaign)."""
    job = Job(kind=kind, payload=payload)
    if run_at is not None:
        job.run_at = run_at
    session.add(job)
    session.flush()
    return job


def claim(session: Session, lease_seconds: float) -> Job | None:
    """Claim one due job (or one whose lease expired) in a single statement; caller commits."""
    due = or_(
        and_(Job.status == "pending", Job.run_at <= NOW),
        and_(Job.status == "running", Job.locked_until < NOW),
    )
    pick = (
        select(Job.id)
        .where(due)
        .order_by(Job.run_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    q = (
        update(Job)
        .where(Job.id == pick)
        .values(
            status="running",
            attempts=Job.attempts + 1,
            locked_until=NOW + timedelta(seconds=lease_seconds),
        )
        .returning(Job)
        .execution_options(synchronize_session=False)
    )
    return session.scalars(q).one_or_none()


def renew(session: Session, job_id: int, lease_seconds: float) -> None:
    q = (
        update(Job)
        .where(Job.id == job_id, Job.status == "running")
        .values(locked_until=NOW + timedelta(seconds=lease_seconds))
    )
    session.execute(q)


def complete(session: Session, job_id: int) -> None:
    q = (
        update(Job)
        .where(Job.id == job_id, Job.status == "running")
        .values(status="done", locked_until=None, last_error=None)
    )
    session.execute(q)


def retry_or_fail(
    session: Session, job_id: int, error: str, delay_seconds: float, max_attempts: int
) -> str | None:
    """pending again after the delay while attempts < max, else failed. Returns the new status."""
    retry = Job.attempts < max_attempts
    q = (
        update(Job)
        .where(Job.id == job_id, Job.status == "running")
        .values(
            status=case((retry, "pending"), else_="failed"),
            run_at=case((retry, NOW + timedelta(seconds=delay_seconds)), else_=Job.run_at),
            locked_until=None,
            last_error=error,
        )
        .returning(Job.status)
    )
    return session.execute(q).scalar_one_or_none()


def get(session: Session, job_id: int) -> Job | None:
    return session.get(Job, job_id)


def advance(session: Session, seconds: int) -> int:
    """Dev clock: make pending jobs due and running leases expire `seconds` sooner."""
    delta = timedelta(seconds=seconds)
    pending = update(Job).where(Job.status == "pending").values(run_at=Job.run_at - delta)
    running = (
        update(Job).where(Job.status == "running").values(locked_until=Job.locked_until - delta)
    )
    return session.execute(pending).rowcount + session.execute(running).rowcount
