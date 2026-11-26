import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import SocialPostEntry, WebhookEvent
from app.repos import campaigns as repo
from app.services import webhooks

client = TestClient(app, raise_server_exceptions=False)
SECRET = "test-webhook-secret"
URL = "/webhook/social-delivery"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", SECRET)


def entry(pid: str | None = "p1", status: str = "publishing") -> int:
    p = client.post("/posts", json={"title": "Spring Sale", "body": "Big news. Come see."})
    c = client.post("/campaigns", json={"post_id": p.json()["id"], "platforms": ["x"]}).json()
    eid = c["entries"][0]["id"]
    with SessionLocal() as s:
        e = s.get(SocialPostEntry, eid)
        e.platform_post_id, e.status = pid, status
        s.commit()
    return eid


def state(eid: int) -> tuple[str, str | None]:
    with SessionLocal() as s:
        e = s.get(SocialPostEntry, eid)
        return e.status, e.last_error


def events() -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(WebhookEvent))


def send(
    pid="p1", status="delivered", event_id="ev-1", ts=None, body=None, headers=None, tamper=None
):
    ts = int(time.time()) if ts is None else ts
    if body is None:
        body = json.dumps({"event_id": event_id, "post_id": pid, "status": status, "timestamp": ts})
    raw = body.encode() if isinstance(body, str) else body
    h = {"X-Timestamp": str(ts), "X-Signature": webhooks.sign(SECRET, str(ts), raw)}
    if headers is not None:
        h = headers
    return client.post(URL, content=tamper(raw) if tamper else raw, headers=h)


def test_signature_matches_fake_platform_scheme():
    from fake_platform.signing import sign

    body = '{"a": 1}'
    assert webhooks.sign("k", "123", body.encode()) == sign("k", 123, body)


def test_valid_event_publishes():
    eid = entry()
    r = send()
    assert (r.status_code, r.json()) == (200, {"result": "applied"})
    assert state(eid) == ("published", None)
    assert events() == 1


def test_failed_event_fails_a_publishing_entry():
    eid = entry()
    assert send(status="failed").json() == {"result": "applied"}
    assert state(eid) == ("failed", "platform reported failure")


def _now():
    return int(time.time())


@pytest.mark.parametrize(
    "kw",
    [
        {"headers": {"X-Timestamp": "1", "X-Signature": "0" * 64}},  # forged
        {"headers": {}},
        {"headers": {"X-Signature": "0" * 64}},
        {"headers": {"X-Timestamp": "abc", "X-Signature": "0" * 64}},
        {"headers": {"X-Timestamp": "1_000", "X-Signature": "0" * 64}},
        {"ts_offset": -301},  # stale past
        {"ts_offset": 301},  # stale future
        {"tamper": lambda b: b.replace(b"delivered", b"Delivered")},  # modified body
        {"body": "{not json"},
        {"body": b"\xff\xfe"},
        {"status": "shipped"},
        {"event_id": ""},
        {"event_id": "x" * 201},
        {"event_id": "a\u0000b"},
        {"pid": 123},
        {"body_ts_offset": 1},  # body timestamp != header
    ],
)
def test_rejected_with_400_and_no_write(kw):
    eid = entry()
    ts = _now() + kw.pop("ts_offset", 0)
    if "body_ts_offset" in kw:
        kw["body"] = json.dumps(
            {
                "event_id": "e",
                "post_id": "p1",
                "status": "delivered",
                "timestamp": ts + kw.pop("body_ts_offset"),
            }
        )
    if kw.get("headers") and kw["headers"].get("X-Timestamp") == "1":
        kw["headers"]["X-Timestamp"] = str(ts)
    r = send(ts=ts, **kw)
    assert r.status_code == 400, r.text
    assert events() == 0
    assert state(eid) == ("publishing", None)


def test_forged_rejection_logs_reason_only(caplog):
    entry()
    ts = _now()
    r = send(headers={"X-Timestamp": str(ts), "X-Signature": "ab" * 32})
    assert (r.status_code, r.json()["detail"]) == (400, "bad signature")
    assert "webhook rejected: bad signature" in caplog.text
    assert SECRET not in caplog.text and "ab" * 32 not in caplog.text


def test_duplicate_processed_once():
    eid = entry()
    assert send().json() == {"result": "applied"}
    with SessionLocal() as s:  # put it back to prove the duplicate changes nothing
        s.get(SocialPostEntry, eid).status = "publishing"
        s.commit()
    assert send().json() == {"result": "duplicate"}
    assert state(eid) == ("publishing", None)
    assert events() == 1


def test_event_before_mark_accepted_ends_published():
    eid = entry(pid=None, status="publishing")
    assert send(pid="p-early").json() == {"result": "unmatched"}  # 201 not back yet
    with SessionLocal() as s:
        repo.mark_accepted(s, eid, "p-early")
        s.commit()
    assert state(eid) == ("published", None)


def test_failed_event_before_mark_accepted_ends_failed():
    eid = entry(pid=None, status="publishing")
    send(pid="p-early", status="failed")
    with SessionLocal() as s:
        repo.mark_accepted(s, eid, "p-early")
        s.commit()
    assert state(eid) == ("failed", "platform reported failure")


def test_published_never_regresses():
    eid = entry(status="published")
    assert send(status="failed").json() == {"result": "unmatched"}
    with SessionLocal() as s:
        repo.mark_accepted(s, eid, "p1")
        repo.record_error(s, eid, "late", "failed")
        repo.mark_publishing(s, eid, 5)
        s.commit()
    assert state(eid) == ("published", None)


def test_unknown_post_is_stored_and_unmatched():
    r = send(pid="nobody")
    assert (r.status_code, r.json()) == (200, {"result": "unmatched"})
    assert events() == 1


def test_enqueue_sets_queued():
    eid = entry(pid=None, status="draft")
    with SessionLocal() as s:
        cid = s.get(SocialPostEntry, eid).campaign_id
    assert client.post(f"/campaigns/{cid}/publish").status_code == 202
    assert state(eid) == ("queued", None)


def test_constant_time_compare_is_used(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(webhooks.hmac, "compare_digest", spy)
    entry()
    assert send().status_code == 200
    assert len(calls) == 1
