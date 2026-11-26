#!/usr/bin/env bash
# Stage 5 tester probe: malformed / hostile input on POST /webhook/social-delivery must be 400 or
# 413, never 500, and must not store anything. Runs inside the api container so WEBHOOK_SECRET
# never leaves it.
set -u
cd "$(dirname "$0")/../.."
docker compose exec -T api python - <<'PY'
import hashlib, hmac, json, os, sys, time, urllib.request, uuid
from sqlalchemy import create_engine, text

URL = "http://localhost:8000/webhook/social-delivery"
SECRET = os.environ["WEBHOOK_SECRET"]
eng = create_engine(os.environ["DATABASE_URL"])
count = lambda: eng.connect().execute(text("select count(*) from webhook_events")).scalar()

def sign(ts, raw):
    return hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()

def post(raw, headers):
    req = urllib.request.Request(URL, data=raw, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code

def signed(body_bytes, ts=None):
    ts = ts or str(int(time.time()))
    return body_bytes, {"X-Timestamp": ts, "X-Signature": sign(ts, body_bytes),
                        "Content-Type": "application/json"}

now = str(int(time.time()))
def ev(**kw):
    d = {"event_id": str(uuid.uuid4()), "post_id": "p-x", "status": "delivered",
         "timestamp": int(now)}
    d.update(kw)
    return json.dumps(d).encode()

cases = [
    ("no headers", ev(), {}),
    ("non-int ts", ev(), {"X-Timestamp": "abc", "X-Signature": "0" * 64}),
    ("huge ts", ev(), {"X-Timestamp": "9" * 40, "X-Signature": "0" * 64}),
    ("negative ts", ev(), {"X-Timestamp": "-5", "X-Signature": "0" * 64}),
    ("non-ascii sig", ev(), {"X-Timestamp": now, "X-Signature": "é" * 64}),
    ("empty sig", ev(), {"X-Timestamp": now, "X-Signature": ""}),
    ("signed non-json", *signed(b"not json")),
    ("signed invalid utf8", *signed(b"\xff\xfe\x00")),
    ("signed json array", *signed(b"[1,2]")),
    ("signed NUL in post_id", *signed(ev(post_id="a\u0000b"))),
    ("signed bad status", *signed(ev(status="published"))),
    ("signed event_id 201 chars", *signed(ev(event_id="e" * 201))),
    ("signed ts as string", *signed(ev(timestamp=now))),
    ("signed future ts +600", *signed(ev(timestamp=int(now) + 600), str(int(now) + 600))),
    ("signed 2 MB body", *signed(b'{"event_id":"' + b"a" * 2_000_000 + b'"}')),
]
before = count()
bad = 0
for name, raw, headers in cases:
    code = post(raw, headers)
    ok = code in (400, 413)
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} -> {code}")
after = count()
print(f"{'PASS' if after == before else 'FAIL'}  no webhook_events rows stored ({before} -> {after})")
bad += after != before
print("ALL PASS" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
PY
