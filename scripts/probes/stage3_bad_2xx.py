"""Stage 3 tester: platform answers 2xx without a usable body. Runs inside the api container:
    docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py
The fake platform has no switch for this, so the api's shared httpx client is swapped for a
MockTransport (no app code edited). Prints one line per case; exit 1 if any case returns 500.
"""

import sys

import httpx
from fastapi.testclient import TestClient

import app.publishers.fake as fake
from app.main import app

SECRET = "probe-secret-tok-9f3a"


def run(name, post_reply, token_reply, platforms=("x",), want=None):
    """want: {platform: (status, attempts, last_error | "ANY")}; default: x failed after 5."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth/token":
            return token_reply()
        return post_reply(req)

    fake._client = httpx.Client(base_url="http://fake", transport=httpx.MockTransport(handler))
    c = TestClient(app, raise_server_exceptions=False)
    pid = c.post("/posts", json={"title": "bad 2xx", "body": "One. Two."}).json()["id"]
    cid = c.post("/campaigns", json={"post_id": pid, "platforms": list(platforms)}).json()["id"]
    # force a token fetch so the token case is exercised
    from app.db import SessionLocal
    from app.models import PlatformToken

    with SessionLocal() as s:
        s.query(PlatformToken).filter(PlatformToken.platform.in_(platforms)).delete()
        s.commit()
    r = c.post(f"/campaigns/{cid}/publish")
    rows = (
        {e["platform"]: (e["status"], e["attempts"], e["last_error"]) for e in r.json()["entries"]}
        if r.status_code == 200
        else None
    )
    want = want or {"x": ("failed", 5, "ANY")}
    ok = r.status_code == 200 and all(
        rows[p][:2] == w[:2] and (bool(rows[p][2]) if w[2] == "ANY" else rows[p][2] == w[2])
        for p, w in want.items()
    )
    ok = ok and SECRET not in repr(rows)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: HTTP {r.status_code} entries={rows}")
    return ok


def boom_once():
    calls = []

    def reply(req):
        calls.append(1)
        if len(calls) == 1:  # first entry's send: a non-httpx error carrying a secret
            raise RuntimeError(f"Authorization: Bearer {SECRET}")
        return httpx.Response(201, json={"id": "p-ok"})

    return reply


def ok_token():
    return httpx.Response(200, json={"access_token": "t-probe", "token_type": "Bearer"})


def ok_post(req):
    return httpx.Response(201, json={"id": "p1"})


results = [
    run("201 {} (no id)", lambda q: httpx.Response(201, json={}), ok_token),
    run("201 non-JSON body", lambda q: httpx.Response(201, text="ok"), ok_token),
    run("201 id is int", lambda q: httpx.Response(201, json={"id": 7}), ok_token),
    run("201 id empty string", lambda q: httpx.Response(201, json={"id": ""}), ok_token),
    run("201 JSON list", lambda q: httpx.Response(201, json=["id"]), ok_token),
    run("201 JSON null", lambda q: httpx.Response(201, content=b"null"), ok_token),
    run("token 200 without access_token", ok_post, lambda: httpx.Response(200, json={})),
    run("token 200 non-JSON", ok_post, lambda: httpx.Response(200, text="<html>")),
    run(
        "token 200 access_token int", ok_post, lambda: httpx.Response(200, json={"access_token": 5})
    ),
    run("token 200 JSON list", ok_post, lambda: httpx.Response(200, json=[SECRET])),
    run(
        "guard: RuntimeError(secret) on 1st entry -> failed(type only), 2nd accepted",
        boom_once(),
        ok_token,
        platforms=("instagram", "x"),
        want={"instagram": ("failed", 1, "RuntimeError"), "x": ("publishing", 1, None)},
    ),
]
# drop the probe's fake token so the live stack re-fetches a real one
from app.db import SessionLocal  # noqa: E402
from app.models import PlatformToken  # noqa: E402

with SessionLocal() as s:
    s.query(PlatformToken).filter(PlatformToken.platform.in_(["x", "instagram"])).delete()
    s.commit()
sys.exit(0 if all(results) else 1)
