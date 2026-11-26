"""Stage 5 / ISSUE-010: the webhook transaction and mark_accepted must not each miss the other's
uncommitted write. Two real sessions; the second writer runs in a thread so that a lock-based
fix (it blocks until the first commits) and the current bug (it does not block) both finish."""

import threading

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import SocialPostEntry
from app.repos import campaigns as entries
from app.repos import webhooks as events

client = TestClient(app)


def _publishing_entry() -> int:
    p = client.post("/posts", json={"title": "Spring Sale", "body": "Big news. Come see."})
    c = client.post("/campaigns", json={"post_id": p.json()["id"], "platforms": ["x"]}).json()
    eid = c["entries"][0]["id"]
    with SessionLocal() as s:
        s.get(SocialPostEntry, eid).status = "publishing"
        s.commit()
    return eid


def _status(eid: int) -> str:
    with SessionLocal() as s:
        return s.get(SocialPostEntry, eid).status


def _in_thread(fn) -> threading.Thread:
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    t.join(timeout=1)  # pre-fix: done at once; with a lock: still waiting
    return t


def _accept(eid: int, pid: str):
    def run():
        with SessionLocal() as s:
            entries.mark_accepted(s, eid, pid)
            s.commit()

    return run


def _deliver(pid: str, event_id: str):
    def run():
        with SessionLocal() as s:
            assert events.store(s, event_id, "{}", pid, "delivered")
            entries.apply_delivery(s, pid, "delivered")
            s.commit()

    return run


def test_webhook_first_uncommitted_then_mark_accepted_ends_published():
    eid = _publishing_entry()
    with SessionLocal() as hook:  # webhook: event stored, UPDATE matches nothing, not committed
        assert events.store(hook, "ev-race-1", "{}", "p-race-1", "delivered")
        assert entries.apply_delivery(hook, "p-race-1", "delivered") is False
        worker = _in_thread(_accept(eid, "p-race-1"))  # the 201 comes back meanwhile
        hook.commit()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert _status(eid) == "published"  # a verified 'delivered' event is stored


def test_mark_accepted_first_uncommitted_then_webhook_ends_published():
    eid = _publishing_entry()
    with SessionLocal() as worker:  # post id written, not committed
        entries.mark_accepted(worker, eid, "p-race-2")
        hook = _in_thread(_deliver("p-race-2", "ev-race-2"))
        worker.commit()
    hook.join(timeout=10)
    assert not hook.is_alive()
    assert _status(eid) == "published"
