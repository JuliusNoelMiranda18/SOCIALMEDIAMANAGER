import hashlib
import logging
import pathlib
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from test_publishers import Fake

from app.db import SessionLocal
from app.main import app
from app.models import SocialPostEntry
from app.publishers.fake import FakeInstagramPublisher, FakeXPublisher
from app.repos import campaigns as repo
from app.services import publishing
from app.worker.runner import run_once

client = TestClient(app, raise_server_exceptions=False)
OK = httpx.Response(201, json={"id": "p1"})


def campaign(platforms=("x",)) -> dict:
    p = client.post("/posts", json={"title": "Spring Sale", "body": "Big news. Come see."})
    r = client.post("/campaigns", json={"post_id": p.json()["id"], "platforms": list(platforms)})
    return r.json()


@pytest.fixture
def wire(monkeypatch):
    """Route the service's publishers to a scripted Fake; returns (fake, sleeps)."""
    sleeps: list[float] = []

    def install(*replies):
        fake = Fake(*replies)
        classes = {"x": FakeXPublisher, "instagram": FakeInstagramPublisher}
        monkeypatch.setattr(publishing, "get_publisher", lambda p: fake.publisher(classes[p]))
        return fake

    monkeypatch.setattr(publishing.random, "uniform", lambda a, b: b)  # worst-case jitter
    install.sleeps = sleeps
    return install


def run(cid, sleeps):
    with SessionLocal() as s:
        return publishing.publish_campaign(s, cid, sleep=sleeps.append)


def test_key_committed_before_first_call(wire):
    c = campaign()
    seen = []
    fake = wire(OK)

    def peek():
        with SessionLocal() as other:  # a second session sees only committed data
            e = other.scalars(select(SocialPostEntry)).one()
            seen.append((e.idempotency_key, e.status))

    fake.on_post = peek
    out = run(c["id"], wire.sleeps)
    want = hashlib.sha256(f"{c['id']}:{c['post_id']}:x".encode()).hexdigest()
    assert seen == [(want, "publishing")]
    assert fake.posts[0].headers["Idempotency-Key"] == want
    e = out.entries[0]
    assert (e.status, e.platform_post_id, e.attempts, e.last_error) == ("publishing", "p1", 1, None)
    assert b"http://api:8000/media/" in fake.posts[0].content


def test_retry_after_honoured_and_same_key(wire):
    c = campaign()
    fake = wire(
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(429, headers={"Retry-After": "2"}),
        OK,
    )
    e = run(c["id"], wire.sleeps).entries[0]
    # max(Retry-After, backoff): backoff ceilings are 0.5 s and 1 s, so Retry-After wins
    assert wire.sleeps == [2, 2]
    assert e.attempts == 3 and e.platform_post_id == "p1"
    assert len({p.headers["Idempotency-Key"] for p in fake.posts}) == 1


def test_backoff_grows_and_is_capped(wire, monkeypatch):
    monkeypatch.setattr(publishing.settings, "publish_max_attempts", 9)
    c = campaign()
    wire(*[httpx.Response(503)] * 9)
    e = run(c["id"], wire.sleeps).entries[0]
    assert wire.sleeps == [0.5, 1, 2, 4, 8, 16, 30, 30]
    assert (e.status, e.attempts, e.last_error) == ("failed", 9, "HTTP 503")


def test_attempts_exhausted_marks_failed(wire):
    c = campaign()
    wire(*[httpx.ReadTimeout("slow")] * 5)
    e = run(c["id"], wire.sleeps).entries[0]
    assert (e.status, e.attempts, e.last_error) == ("failed", 5, "ReadTimeout")
    assert len(wire.sleeps) == 4


def test_retry_after_too_long_fails_without_waiting(wire):
    c = campaign()
    wire(httpx.Response(429, headers={"Retry-After": "61"}))
    e = run(c["id"], wire.sleeps).entries[0]
    assert e.status == "failed" and "exceeds MAX_RETRY_AFTER_SECONDS=60" in e.last_error
    assert wire.sleeps == []


def test_fatal_stops_immediately(wire):
    c = campaign()
    wire(httpx.Response(400))
    e = run(c["id"], wire.sleeps).entries[0]
    assert (e.status, e.attempts, e.last_error) == ("failed", 1, "HTTP 400")


def test_publishing_twice_sends_no_second_post(wire):
    c = campaign(["instagram", "x"])
    fake = wire(OK, OK)
    run(c["id"], wire.sleeps)
    out = run(c["id"], wire.sleeps)
    assert len(fake.posts) == 2
    assert {e.platform: e.attempts for e in out.entries} == {"instagram": 1, "x": 1}


def test_token_never_logged(wire, caplog):
    caplog.set_level(logging.DEBUG)
    c = campaign()
    fake = wire(httpx.Response(401), OK)
    run(c["id"], wire.sleeps)
    assert fake.issued == ["tok0", "tok1"]
    for t in fake.issued:
        assert t not in caplog.text


def test_endpoint(wire):
    """Publish is enqueued (202); the worker runs publish_campaign."""
    c = campaign(["instagram", "x"])
    wire(OK, OK)
    r = client.post(f"/campaigns/{c['id']}/publish")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert run_once()
    e = client.get(f"/campaigns/{c['id']}").json()["entries"][0]
    assert (e["status"], e["attempts"], e["last_error"], e["platform_post_id"]) == (
        "publishing",
        1,
        None,
        "p1",
    )
    assert client.post(f"/campaigns/{c['id']}/publish").status_code == 202  # replay: a no-op job
    assert run_once()
    assert [e["attempts"] for e in client.get(f"/campaigns/{c['id']}").json()["entries"]] == [1, 1]


@pytest.mark.parametrize("cid,code", [(999, 404), (0, 422), ("abc", 422), (2**63, 422)])
def test_endpoint_bad_ids(cid, code):
    assert client.post(f"/campaigns/{cid}/publish").status_code == code


def test_services_import_no_adapter_class():
    src = "\n".join(p.read_text() for p in pathlib.Path("app/services").glob("*.py"))
    for name in ("FakeInstagramPublisher", "FakeXPublisher", "app.publishers.fake"):
        assert name not in src


def test_unexpected_error_fails_one_entry_and_continues(wire, monkeypatch):
    c = campaign(["instagram", "x"])
    fake = wire(OK)

    def get_publisher(platform):
        if platform == "instagram":
            raise RuntimeError("secret-ish detail")
        return fake.publisher()

    monkeypatch.setattr(publishing, "get_publisher", get_publisher)
    assert client.post(f"/campaigns/{c['id']}/publish").status_code == 202
    assert run_once()
    r = client.get(f"/campaigns/{c['id']}")
    got = {e["platform"]: (e["status"], e["last_error"]) for e in r.json()["entries"]}
    assert got == {"instagram": ("failed", "RuntimeError"), "x": ("publishing", None)}


def test_malformed_2xx_ends_failed_with_reason(wire):
    c = campaign()
    fake = wire(*[httpx.Response(201, json={})] * 5)
    e = run(c["id"], wire.sleeps).entries[0]
    assert (e.status, e.attempts, e.last_error) == ("failed", 5, "malformed response")
    assert len({p.headers["Idempotency-Key"] for p in fake.posts}) == 1


def test_exhausted_entry_is_not_retried(wire):
    c = campaign()
    fake = wire(*[httpx.Response(503)] * 5)
    run(c["id"], wire.sleeps)
    e = run(c["id"], wire.sleeps).entries[0]  # second publish: cap already reached
    assert (e.status, e.attempts, e.last_error) == ("failed", 5, "HTTP 503")
    assert len(fake.posts) == 5


def test_concurrent_publishes_share_the_attempt_cap(monkeypatch):
    """ISSUE-008: two publishes of one entry send at most PUBLISH_MAX_ATTEMPTS in total."""
    c = campaign()
    fake, lock = Fake(*[httpx.Response(503)] * 10), threading.Lock()

    def handler(request):
        with lock:  # Fake's reply list is not thread-safe
            return fake(request)

    pub = FakeXPublisher(httpx.Client(transport=httpx.MockTransport(handler), base_url="http://f"))
    monkeypatch.setattr(publishing, "get_publisher", lambda p: pub)

    def one():
        with SessionLocal() as s:
            publishing.publish_campaign(s, c["id"], sleep=lambda _: time.sleep(0.01))

    threads = [threading.Thread(target=one) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with SessionLocal() as s:
        e = s.scalars(select(SocialPostEntry)).one()
    assert e.attempts == len(fake.posts) == 5
    assert e.status == "failed"


@pytest.mark.parametrize("preset", [0, 4])  # mid-retry error, and a final-attempt failure
def test_late_failure_never_overwrites_accepted(wire, preset):
    """ISSUE-009: a concurrent publish is accepted while ours is in flight; our 503 must not
    mark the entry failed or leave a last_error, and we stop retrying."""
    c = campaign()
    with SessionLocal() as s:
        s.execute(update(SocialPostEntry).values(attempts=preset))
        s.commit()
    fake = wire(httpx.Response(503), OK)

    def other_publish_accepted():
        with SessionLocal() as other:
            e = other.scalars(select(SocialPostEntry)).one()
            repo.mark_accepted(other, e.id, "p-other")
            other.commit()

    fake.on_post = other_publish_accepted
    e = run(c["id"], wire.sleeps).entries[0]
    assert (e.status, e.platform_post_id, e.last_error) == ("publishing", "p-other", None)
    assert e.attempts == preset + 1 and len(fake.posts) == 1


def test_late_publishing_write_never_undoes_failed():
    """A request that read the entry before a concurrent publish used the last attempt and
    failed it must not flip it back to 'publishing' (the stress probe's publishing-no-id)."""
    campaign()
    with SessionLocal() as s:
        failed = {"attempts": 5, "status": "failed", "last_error": "HTTP 503"}
        s.execute(update(SocialPostEntry).values(**failed))
        s.commit()
        e = s.scalars(select(SocialPostEntry)).one()
        repo.mark_publishing(s, e.id, 5)
        repo.record_error(s, e.id, "HTTP 502", "publishing")  # an earlier attempt's late retry
        s.commit()
        s.refresh(e)
    assert (e.status, e.last_error) == ("failed", "HTTP 503")
