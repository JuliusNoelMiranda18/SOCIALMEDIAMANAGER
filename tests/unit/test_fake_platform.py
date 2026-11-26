import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from fake_platform import main
from fake_platform.signing import sign

POST = {"platform": "x", "caption": "hi", "image_url": None}


@pytest.fixture
def c(monkeypatch):
    client = TestClient(main.app)
    client.post("/_control/reset")
    sent = []
    monkeypatch.setattr(main, "deliver", lambda url, body, headers: sent.append((body, headers)))
    client.sent = sent
    return client


def auth(c):
    r = c.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "client_id": "a", "client_secret": "b"},
    )
    assert r.status_code == 200 and r.json()["token_type"] == "Bearer"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def post(c, h, key="k1"):
    return c.post("/v1/posts", json=POST, headers={**h, "Idempotency-Key": key})


def test_token_bad_requests(c):
    assert c.post("/oauth/token", data={"grant_type": "password"}).status_code == 400
    assert c.post("/oauth/token").status_code == 400
    assert c.post("/oauth/token", content=b"\xff\xfe{").status_code == 400


def test_auth_and_key_required(c):
    h = auth(c)
    assert c.post("/v1/posts", json=POST, headers={"Idempotency-Key": "k"}).status_code == 401
    bad = {"Authorization": "Bearer nope", "Idempotency-Key": "k"}
    assert c.post("/v1/posts", json=POST, headers=bad).status_code == 401
    assert c.post("/v1/posts", json=POST, headers=h).status_code == 400
    assert (
        c.post(
            "/v1/posts", json={"platform": "tiktok"}, headers={**h, "Idempotency-Key": "k"}
        ).status_code
        == 422
    )


def test_idempotent_replay(c):
    h = auth(c)
    r1, r2 = post(c, h), post(c, h)
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert len(c.get("/_posts").json()) == 1
    assert len(c.sent) == 1  # replay sends no callback
    assert c.get("/_posts").json()[0]["idempotency_key"] == "k1"


def test_rate_limit(c):
    h = auth(c)
    c.post("/_control", json={"rate_limit": {"enabled": True, "retry_after_seconds": 7}})
    r = post(c, h)
    assert r.status_code == 429 and r.headers["Retry-After"] == "7"
    assert c.get("/_posts").json() == []


def test_rate_limit_count_and_http_date(c):
    h = auth(c)
    rl = {"enabled": True, "retry_after_seconds": 3, "count": 2, "format": "http-date"}
    c.post("/_control", json={"rate_limit": rl})
    r1, r2 = post(c, h, "a"), post(c, h, "a")
    assert r1.status_code == r2.status_code == 429
    when = parsedate_to_datetime(r1.headers["Retry-After"])
    assert 3 <= (when - datetime.now(UTC)).total_seconds() <= 4  # rounded up, never early
    assert post(c, h, "a").status_code == 201  # switch turned itself off
    assert c.get("/_control").json()["rate_limit"]["enabled"] is False
    assert post(c, h, "b").status_code == 201


def test_stats_and_tokens(c):
    h = auth(c)
    c.post("/v1/posts", json=POST, headers={"Idempotency-Key": "k"})  # 401 is recorded too
    post(c, h, "k1")
    post(c, h, "k1")
    rows = c.get("/_stats").json()["post_requests"]
    assert [(r["idempotency_key"], r["status"]) for r in rows] == [
        ("k", 401),
        ("k1", 201),
        ("k1", 201),
    ]
    assert datetime.fromisoformat(rows[0]["at"]).tzinfo is not None
    assert c.get("/_tokens").json() == [h["Authorization"].split()[1]]
    c.post("/_control/reset")
    assert c.get("/_stats").json() == {"post_requests": []} and c.get("/_tokens").json() == []


def test_failure_rate(c):
    h = auth(c)
    c.post("/_control", json={"failure_rate": 1.0})
    assert post(c, h).status_code == 503 and c.get("/_posts").json() == []
    c.post("/_control", json={"failure_rate": 0.0})
    assert post(c, h).status_code == 201


def test_drop_response(c):
    h = auth(c)
    c.post("/_control", json={"drop_response": {"enabled": True, "delay_seconds": 1}})
    t = time.monotonic()
    first = post(c, h)
    assert time.monotonic() - t >= 1
    t = time.monotonic()
    retry = post(c, h)
    assert time.monotonic() - t < 0.5 and retry.json() == first.json()
    assert len(c.get("/_posts").json()) == 1


def test_callback_signature(c):
    h = auth(c)
    post(c, h)
    body, hd = c.sent[0]
    assert hd["X-Signature"] == sign(settings.webhook_secret, hd["X-Timestamp"], body)
    c.post("/_control", json={"forged_signature": True})
    post(c, h, key="k2")
    body, hd = c.sent[1]
    assert hd["X-Signature"] != sign(settings.webhook_secret, hd["X-Timestamp"], body)


def test_unreachable_webhook_does_not_fail_post(c, monkeypatch):
    def boom(*a):
        raise OSError("down")

    monkeypatch.setattr(main, "deliver", boom)
    assert post(c, auth(c)).status_code == 201


def test_control_get_set_reset_validation(c):
    r = c.post("/_control", json={"webhook_url": "http://x/y", "forged_signature": True})
    assert r.json()["webhook_url"] == "http://x/y"
    assert c.get("/_control").json()["forged_signature"] is True
    assert c.post("/_control/reset").json()["forged_signature"] is False
    for bad in (
        {"failure_rate": 1.5},
        {"failure_rate": "a"},
        {"rate_limit": {"enabled": True, "retry_after_seconds": -1}},
        {"drop_response": {"delay_seconds": "x"}},
        {"forged_signature": "maybe"},
        {"bogus": 1},
    ):
        assert c.post("/_control", json=bad).status_code == 422, bad
    assert c.post("/_control", content=b"{bad").status_code == 422


def test_reset_clears_state(c):
    h = auth(c)
    post(c, h)
    c.post("/_control/reset")
    assert c.get("/_posts").json() == []
    assert post(c, h).status_code == 401  # tokens cleared
    assert c.get("/nope").status_code == 404


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_failure_rate_is_422(c, bad):
    body = f'{{"failure_rate": {bad}}}'
    r = c.post("/_control", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert c.get("/_control").json()["failure_rate"] == 0.0


def test_nested_partial_update_merges(c):
    c.post("/_control", json={"rate_limit": {"enabled": True, "retry_after_seconds": 11}})
    c.post("/_control", json={"rate_limit": {"enabled": False}})
    rl = c.get("/_control").json()["rate_limit"]
    assert rl == {"enabled": False, "retry_after_seconds": 11, "count": None, "format": "seconds"}
    c.post("/_control", json={"drop_response": {"delay_seconds": 5}})
    assert c.get("/_control").json()["drop_response"] == {"enabled": False, "delay_seconds": 5}
