import logging
import time

from app.config import settings
from app.worker.runner import run_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # request lines are noise here
log = logging.getLogger("worker")
log.info("worker started")

while True:
    try:
        busy = run_once()
    except Exception as e:  # e.g. the DB is briefly down: the loop never dies
        log.warning("worker loop error: %s", type(e).__name__)
        busy = False
    if not busy:
        time.sleep(settings.worker_poll_seconds)
