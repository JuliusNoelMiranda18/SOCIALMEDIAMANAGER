import importlib
import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from test_publishers import Fake

import app.main
from app.db import SessionLocal
from app.models import Job
from app.publishers.fake import FakeInstagramPublisher, FakeXPublisher
from app.repos import jobs as repo
from app.services import publishing
from app.worker import runner
from app.worker.runner import run_once

client = TestClient(app.main.app, raise_server_exceptions=False)


def campaign(platforms=("x",)) -> int:
    p = client.post("/posts", json={"title": "Spring Sale", "body": "Big news. Come see."})
    r = client.post("/campaigns", json={"post_id": p.json()["id"], "platforms": list(platforms)})
    return r.json()["id"]


def add_job(cid: int, **fields) -> int:
    with SessionLocal() as s:
        job = Job(kind="publish_campaign", payload={"campaign_id": cid}, **fields)
        s.add(job)
        s.commit()
        return job.id


def job(job_id: int) -> Job:
    with SessionLocal() as s:
        return s.get(Job, job_id)


def db_now():
    with SessionLocal() as s:
        return s.scalar(select(func.localtimestamp()))


def test_concurrent_claims_never_take_the_same_job():
    a, b = add_job(1), add_job(2)
    with SessionLocal() as s1, SessionLocal() as s2:
        j1 = repo.claim(s1, 30)  # row lock held until commit
        j2 = repo.claim(s2, 30)  # SKIP LOCKED: takes the other job
        j3 = repo.claim(s2, 30)  # nothing left
        assert {j1.id, j2.id} == {a, b} and j3 is None
        s1.commit()
        s2.commit()
    assert [job(i).status for i in (a, b)] == ["running", "running"]
    assert job(a).attempts == 1


def test_future_job_is_not_claimed():
    add_job(1, run_at=db_now() + timedelta(minutes=5))
    with SessionLocal() as s:
        assert repo.claim(s, 30) is None


def test_expired_lease_is_reclaimed_but_live_one_is_not():
    now = db_now()
    live = add_job(1, status="running", attempts=1, locked_until=now + timedelta(seconds=30))
    dead = add_job(2, status="running", attempts=1, locked_until=now - timedelta(seconds=1))
    with SessionLocal() as s:
        got = repo.claim(s, 30)
        assert got.id == dead and got.attempts == 2
        assert repo.claim(s, 30) is None
        s.commit()
    assert job(live).attempts == 1


def test_handler_error_retries_later_then_fails(monkeypatch):
    monkeypatch.setitem(runner.HANDLERS, "publish_campaign", lambda s, p: 1 / 0)
    monkeypatch.setattr(runner.settings, "job_max_attempts", 2)
    monkeypatch.setattr(runner.publishing, "backoff_seconds", lambda attempt: 30)
    j = add_job(1)
    assert run_once()
    got = job(j)
    assert (got.status, got.attempts, got.locked_until) == ("pending", 1, None)
    assert got.last_error == "ZeroDivisionError: division by zero"
    assert got.run_at > db_now() + timedelta(seconds=25)  # backoff: not due yet
    assert not run_once()
    with SessionLocal() as s:
        repo.advance(s, 60)
        s.commit()
    assert run_once()
    got = job(j)
    assert (got.status, got.attempts) == ("failed", 2)
    assert not run_once()


def test_heartbeat_keeps_the_lease_alive(monkeypatch):
    monkeypatch.setattr(runner.settings, "job_lease_seconds", 0.3)
    seen = []

    def slow(session, payload):
        time.sleep(0.6)  # twice the lease: only the heartbeat keeps it in the future
        with SessionLocal() as other:
            row = other.get(Job, j)
            seen.append(row.locked_until > other.scalar(select(func.localtimestamp())))

    monkeypatch.setitem(runner.HANDLERS, "publish_campaign", slow)
    j = add_job(1)
    assert run_once()
    assert seen == [True]
    assert job(j).status == "done"


def test_run_once_publishes_the_campaign(monkeypatch):
    cid = campaign(["instagram", "x"])
    fake = Fake(httpx.Response(201, json={"id": "p1"}), httpx.Response(201, json={"id": "p2"}))
    classes = {"x": FakeXPublisher, "instagram": FakeInstagramPublisher}
    monkeypatch.setattr(publishing, "get_publisher", lambda p: fake.publisher(classes[p]))
    jid = client.post(f"/campaigns/{cid}/publish").json()["id"]
    assert run_once() and not run_once()
    got = client.get(f"/jobs/{jid}").json()
    assert (got["status"], got["attempts"], got["last_error"], got["locked_until"]) == (
        "done",
        1,
        None,
        None,
    )
    entries = client.get(f"/campaigns/{cid}").json()["entries"]
    assert sorted(e["platform_post_id"] for e in entries) == ["p1", "p2"]
    assert len(fake.posts) == 2


def test_schedule_endpoint():
    cid = campaign()
    r = client.post(f"/campaigns/{cid}/schedule", json={"run_at": "2030-01-01T09:00:00+02:00"})
    assert r.status_code == 202
    body = r.json()
    assert (body["kind"], body["campaign_id"], body["status"], body["attempts"]) == (
        "publish_campaign",
        cid,
        "pending",
        0,
    )
    assert body["run_at"].startswith("2030-01-01T07:00:00")  # stored as UTC
    assert client.get(f"/jobs/{body['id']}").json() == body
    again = client.post(f"/campaigns/{cid}/schedule", json={"run_at": "2030-01-01T09:00:00Z"})
    assert again.status_code == 409
    assert client.post(f"/campaigns/{cid}/publish").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"run_at": "2026-01-01T00:00:00"},  # naive
        {"run_at": "tomorrow"},
        {"run_at": "9999-12-31T23:59:59-14:00"},  # beyond the datetime range in UTC
        {},
    ],
)
def test_schedule_bad_body_is_422(body):
    assert client.post(f"/campaigns/{campaign()}/schedule", json=body).status_code == 422


def test_schedule_missing_campaign_is_404():
    r = client.post("/campaigns/999/schedule", json={"run_at": "2030-01-01T00:00:00Z"})
    assert r.status_code == 404


def test_past_run_at_runs_at_once():
    cid = campaign()
    client.post(f"/campaigns/{cid}/schedule", json={"run_at": "2020-01-01T00:00:00Z"})
    with SessionLocal() as s:
        assert repo.claim(s, 30).campaign_id == cid


def test_publish_is_202_and_get_job_404():
    cid = campaign()
    r = client.post(f"/campaigns/{cid}/publish")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert client.post("/campaigns/999/publish").status_code == 404
    assert client.get("/jobs/999").status_code == 404
    assert client.get("/jobs/0").status_code == 422


def test_advance_time_shifts_pending_and_running(monkeypatch):
    now = db_now()
    p = add_job(1, run_at=now + timedelta(seconds=100))
    r = add_job(2, status="running", locked_until=now + timedelta(seconds=100))
    add_job(3, status="done")
    res = client.post("/_dev/advance-time", json={"seconds": 60})
    assert res.status_code == 200 and res.json() == {"shifted": 2}
    assert job(p).run_at == now + timedelta(seconds=40)
    assert job(r).locked_until == now + timedelta(seconds=40)
    for bad in (0, 86401, 1.5, "60", True):
        assert client.post("/_dev/advance-time", json={"seconds": bad}).status_code == 422


def test_advance_time_is_404_when_flag_off(monkeypatch):
    monkeypatch.setattr(app.main.settings, "dev_endpoints", False)
    off = importlib.reload(app.main).app
    try:
        assert TestClient(off).post("/_dev/advance-time", json={"seconds": 1}).status_code == 404
    finally:
        monkeypatch.undo()
        importlib.reload(app.main)


def test_one_active_job_per_campaign_in_db():
    add_job(1)
    add_job(1, status="done")  # finished jobs do not count
    with pytest.raises(Exception, match="uq_jobs_active_campaign"):
        add_job(1, status="running")
    with SessionLocal() as s:
        s.execute(update(Job).values(status="failed"))
        s.commit()
    add_job(1)  # a failed job no longer blocks a new one
