"""Claim one due job, run it under a heartbeat lease, record the outcome."""

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.repos import jobs as repo
from app.services import publishing

log = logging.getLogger("worker")

# kind -> handler(session, payload). Re-runs are safe: publish_campaign skips accepted entries
# and reuses each in-flight entry's committed idempotency key (ADR-002).
HANDLERS: dict[str, Callable[[Session, dict], object]] = {
    "publish_campaign": lambda s, p: publishing.publish_campaign(s, p["campaign_id"]),
}


def _heartbeat(session_factory, job_id: int, lease: float, stop: threading.Event) -> None:
    while not stop.wait(lease / 3):
        try:
            with session_factory() as s:
                repo.renew(s, job_id, lease)
                s.commit()
        except Exception as e:  # a missed beat is retried next tick; the lease covers 3 ticks
            log.warning("job %s heartbeat failed: %s", job_id, type(e).__name__)


def run_once(session_factory=SessionLocal) -> bool:
    """Run one job if any is due. Returns False when there was nothing to claim."""
    lease = settings.job_lease_seconds
    with session_factory() as s:
        job = repo.claim(s, lease)
        s.commit()  # the claim is durable before the job runs
    if job is None:
        return False
    log.info("job %s claimed kind=%s attempt=%s", job.id, job.kind, job.attempts)
    stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat, args=(session_factory, job.id, lease, stop), daemon=True
    )
    beat.start()
    error = None
    try:
        with session_factory() as s:
            HANDLERS[job.kind](s, job.payload)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:200]
        log.info("job %s raised %s", job.id, type(e).__name__)  # type only: no secrets in logs
    finally:
        stop.set()
        beat.join()
    with session_factory() as s:
        if error is None:
            repo.complete(s, job.id)
            status = "done"
        else:
            delay = publishing.backoff_seconds(job.attempts)
            status = repo.retry_or_fail(s, job.id, error, delay, settings.job_max_attempts)
        s.commit()
    log.info("job %s %s", job.id, status)
    return True
