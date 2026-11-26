# ruff: noqa: E501, B905  (long SQL literals; host python3 is 3.9, so no zip(strict=))
"""Stage 3 tester probe (regression suite). Host python3 (stdlib only). Needs `make up`.
    python3 scripts/probes/stage3_tester.py
Independent checks for probes 1, 2, 6 plus edge cases (bad ids, concurrency, token tampering).
Resets the fake platform switches at the end.
"""

import hashlib
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

B, F = "http://localhost:8000", "http://localhost:9000"
FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f" (got {got!r}, want {want!r})"))
    if not ok:
        FAILS.append(name)


def http(method, url, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")


def psql(sql):
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"',
        "_",
        sql,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def reset():
    http("POST", F + "/_control/reset")


def ctl(body):
    s, _ = http("POST", F + "/_control", body)
    assert s == 200, s


def campaign(platforms):
    _, p = http("POST", B + "/posts", {"title": "Stage 3 tester", "body": "We launched. Come see."})
    s, c = http("POST", B + "/campaigns", {"post_id": p["id"], "platforms": platforms})
    assert s in (200, 201), (s, c)
    return c["id"], p["id"]


def publish(cid):
    return http("POST", f"{B}/campaigns/{cid}/publish")


def stats(key=None, skip401=True):
    rows = http("GET", F + "/_stats")[1]["post_requests"]
    return [
        r
        for r in rows
        if (key is None or r["idempotency_key"] == key) and not (skip401 and r["status"] == 401)
    ]


def gaps(rows):
    t = [datetime.fromisoformat(r["at"]).timestamp() for r in rows]
    return [round(b - a, 2) for a, b in zip(t, t[1:])]


def posts_with(key):
    return sum(p["idempotency_key"] == key for p in http("GET", F + "/_posts")[1])


def entry(resp, platform):
    return next(e for e in resp["entries"] if e["platform"] == platform)


def key_of(cid, platform):
    return psql(
        f"select idempotency_key from social_post_entries "
        f"where campaign_id={cid} and platform='{platform}'"
    )


# ---------------------------------------------------------------- probe 1
def probe1():
    print("== P1 key committed before the network call (row inspected mid-flight)")
    reset()
    ctl({"drop_response": {"enabled": True, "delay_seconds": 8}})
    cid, pid = campaign(["x"])
    out = {}
    t = threading.Thread(target=lambda: out.update(r=publish(cid)))
    t0 = time.time()
    t.start()
    time.sleep(1.5)
    row = psql(
        f"select idempotency_key||'|'||status||'|'||attempts||'|'||"
        f"coalesce(platform_post_id,'NULL') from social_post_entries where campaign_id={cid}"
    )
    want_key = hashlib.sha256(f"{cid}:{pid}:x".encode()).hexdigest()
    in_flight = stats(want_key)
    # Since ISSUE-008 the attempt is counted and committed before the send, so attempts is 1
    # mid-flight; the property is still "key committed before the network call returned".
    check(
        "mid-flight row: key=sha256(cid:pid:x), publishing, attempts 1, no post id",
        row,
        f"{want_key}|publishing|1|NULL",
    )
    check(
        "mid-flight: the platform already received a request with that key",
        len(in_flight) >= 1,
        True,
    )
    ctl({"drop_response": {"enabled": False}})
    t.join()
    s, r = out["r"]
    print(f"      publish took {time.time() - t0:.1f}s")
    check("after timeout+retry: 200", s, 200)
    e = entry(r, "x")
    check(
        "after timeout+retry: post id stored, status publishing, attempts 2",
        (bool(e["platform_post_id"]), e["status"], e["attempts"]),
        (True, "publishing", 2),
    )
    check("exactly 1 post on platform for the key", posts_with(want_key), 1)
    check("platform got 2 requests with the same key", len(stats(want_key)), 2)

    print("== P1 publish twice -> no new post, no new request")
    before = len(stats(skip401=False))
    s, r2 = publish(cid)
    check("second publish 200 and unchanged", (s, entry(r2, "x")["attempts"]), (200, 2))
    check("no new POST /v1/posts", len(stats(skip401=False)), before)
    check("still exactly 1 post", posts_with(want_key), 1)


# ---------------------------------------------------------------- probe 2
def probe2():
    for fmt in ("seconds", "http-date"):
        print(f"== P2 429 x2 Retry-After 3 ({fmt})")
        reset()
        ctl({"rate_limit": {"enabled": True, "retry_after_seconds": 3, "count": 2, "format": fmt}})
        cid, _ = campaign(["instagram"])
        s, r = publish(cid)
        k = key_of(cid, "instagram")
        rows = stats(k)
        g = gaps(rows)
        print(f"      gaps {g}")
        check(
            f"{fmt}: 200, accepted, attempts 3",
            (s, bool(entry(r, "instagram")["platform_post_id"]), entry(r, "instagram")["attempts"]),
            (200, True, 3),
        )
        check(f"{fmt}: statuses [429,429,201]", [x["status"] for x in rows], [429, 429, 201])
        check(f"{fmt}: every gap >= 3 s", all(x >= 3 for x in g), True)
        check(
            f"{fmt}: no gap > 5 s (waits ~Retry-After, not much more)", all(x <= 5 for x in g), True
        )

    print("== P2 Retry-After above MAX_RETRY_AFTER_SECONDS (60) -> failed without waiting")
    reset()
    ctl({"rate_limit": {"enabled": True, "retry_after_seconds": 120, "count": 1}})
    cid, _ = campaign(["x"])
    t0 = time.time()
    s, r = publish(cid)
    dt = time.time() - t0
    e = entry(r, "x")
    print(f"      took {dt:.2f}s, last_error={e['last_error']!r}")
    check("status failed, attempts 1", (s, e["status"], e["attempts"]), (200, "failed", 1))
    check("returned in < 3 s", dt < 3, True)
    check(
        "last_error names MAX_RETRY_AFTER_SECONDS",
        "MAX_RETRY_AFTER_SECONDS" in (e["last_error"] or ""),
        True,
    )
    check("exactly 1 request sent", len(stats(key_of(cid, "x"))), 1)
    print("== P2 failed entry is retried with the same key on the next publish")
    k1 = key_of(cid, "x")
    s, r = publish(cid)  # rate limit auto-off after count=1
    e = entry(r, "x")
    check(
        "retry: accepted, same key, attempts 2",
        (bool(e["platform_post_id"]), key_of(cid, "x") == k1, e["attempts"]),
        (True, True, 2),
    )

    print("== P2 failure_rate 1.0 -> capped at PUBLISH_MAX_ATTEMPTS (5), backoff not hammering")
    totals = []
    for run in range(3):
        reset()
        ctl({"failure_rate": 1.0})
        cid, _ = campaign(["x"])
        t0 = time.time()
        s, r = publish(cid)
        dt = time.time() - t0
        e = entry(r, "x")
        rows = stats(key_of(cid, "x"))
        g = gaps(rows)
        totals.append(g)
        print(f"      run {run}: {dt:.1f}s gaps {g} last_error={e['last_error']!r}")
        check(
            f"run {run}: failed, attempts 5, 5 requests (all 503)",
            (e["status"], e["attempts"], [x["status"] for x in rows]),
            ("failed", 5, [503] * 5),
        )
        ceil = [0.5, 1, 2, 4]  # full jitter ceilings for attempts 1..4
        check(
            f"run {run}: each gap <= its jitter ceiling (+0.3s)",
            all(x <= c + 0.3 for x, c in zip(g, ceil)),
            True,
        )
    mean = [round(sum(t[i] for t in totals) / len(totals), 2) for i in range(4)]
    print(f"      mean gap per step over 3 runs: {mean} (ceilings 0.5,1,2,4)")
    check(
        "mean late gaps > mean early gaps (backoff grows)",
        mean[2] + mean[3] > mean[0] + mean[1],
        True,
    )
    ctl({"failure_rate": 0.0})


# ---------------------------------------------------------------- probe 6
def dump_and_logs():
    dump = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "sh",
            "-c",
            'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"',
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-color"], capture_output=True, text=True
    ).stdout
    return dump, logs


def probe6():
    print("== P6 no plaintext token in pg_dump or ANY container log")
    reset()
    cid, _ = campaign(["instagram", "x"])
    s, r = publish(cid)
    check("publish 200", s, 200)
    print("== P6 tamper ciphertext (flip first byte) -> re-fetch, publish ok")
    old = psql("select encode(ciphertext,'hex') from platform_tokens where platform='x'")
    psql(
        "update platform_tokens set ciphertext = overlay(ciphertext placing "
        "decode(lpad(to_hex(get_byte(ciphertext,0) # 255),2,'0'),'hex') from 1 for 1) where platform='x'"
    )
    cid, _ = campaign(["x"])
    s, r = publish(cid)
    check(
        "tampered ciphertext: 200 accepted",
        (s, bool(entry(r, "x")["platform_post_id"]) if s == 200 else r),
        (200, True),
    )
    check(
        "row replaced with fresh ciphertext",
        psql("select encode(ciphertext,'hex') from platform_tokens where platform='x'") != old,
        True,
    )

    print("== P6 tamper nonce (same length, 12 bytes) -> re-fetch, publish ok")
    psql(
        "update platform_tokens set nonce = decode('000000000000000000000000','hex') where platform='x'"
    )
    cid, _ = campaign(["x"])
    s, r = publish(cid)
    check(
        "tampered 12-byte nonce: 200 accepted",
        (s, bool(entry(r, "x")["platform_post_id"]) if s == 200 else r),
        (200, True),
    )

    print("== P6 corrupt token rows (ISSUE-006): each -> 200 accepted, fresh 12-byte row stored")
    corruptions = [
        ("4-byte nonce", "nonce = decode('00000000','hex')"),
        ("empty nonce", "nonce = ''::bytea"),
        ("200-byte nonce", "nonce = decode(repeat('ab',200),'hex')"),
        ("empty ciphertext", "ciphertext = ''::bytea"),
        ("1-byte ciphertext", "ciphertext = decode('01','hex')"),
        (
            "ciphertext minus last byte",
            "ciphertext = substring(ciphertext from 1 for length(ciphertext)-1)",
        ),
    ]
    for name, setter in corruptions:
        old = psql("select encode(ciphertext,'hex') from platform_tokens where platform='x'")
        psql(f"update platform_tokens set {setter} where platform='x'")
        cid, _ = campaign(["x"])
        s, r = publish(cid)
        e = entry(r, "x") if s == 200 else {}
        print(
            f"      {name}: status {s} entry {e.get('status')}|{e.get('attempts')}|{e.get('last_error')}"
        )
        check(
            f"{name}: 200 accepted, attempts 1",
            (s, bool(e.get("platform_post_id")), e.get("attempts")),
            (200, True, 1),
        )
        check(
            f"{name}: row replaced, 12-byte nonce, new ciphertext",
            psql(
                "select length(nonce)||'|'||(encode(ciphertext,'hex') <> '"
                + old
                + "')::text from platform_tokens where platform='x'"
            ),
            "12|true",
        )

    print("== P6 truncated ciphertext (5 bytes) -> must not 500")
    s, _ = publish(campaign(["x"])[0])  # re-create a good row first
    psql("update platform_tokens set ciphertext = decode('0102030405','hex') where platform='x'")
    cid, _ = campaign(["x"])
    s, r = publish(cid)
    check(
        "truncated ciphertext: no 500",
        (s, s == 200 and bool(entry(r, "x")["platform_post_id"])),
        (200, True),
    )

    toks = http("GET", F + "/_tokens")[1]
    dump, logs = dump_and_logs()
    check("tokens issued", len(toks) >= 2, True)
    check("pg_dump has platform_tokens data", "COPY public.platform_tokens" in dump, True)
    check("no token in pg_dump", [t for t in toks if t in dump], [])
    check(
        "no token in any container log (db, api, worker, fake-platform, web)",
        [t for t in toks if t in logs],
        [],
    )
    check("no 'Bearer' in any container log", "bearer" in logs.lower(), False)
    check(
        "ciphertexts and nonces distinct per row",
        psql(
            "select count(distinct ciphertext)||'/'||count(distinct nonce)||'/'||count(*) from platform_tokens"
        ),
        "2/2/2",
    )


# ---------------------------------------------------------------- edges
def edges():
    print("== bad ids / unknown campaign / wrong method")
    for cid, want in [
        ("999999999", 404),
        ("0", 422),
        ("-1", 422),
        ("abc", 422),
        ("1.5", 422),
        ("9223372036854775808", 422),
        ("%00", 422),
        ("1e3", 422),
    ]:
        s, _ = publish(cid)
        check(f"POST /campaigns/{cid}/publish -> {want}", s, want)
    s, _ = http("GET", B + "/campaigns/1/publish")
    check("GET publish -> 405", s, 405)
    s, _ = http("POST", B + "/campaigns/1/publish?x=1", {"junk": [1, 2]})
    check("publish with a junk body/query is not 500", s != 500, True)

    print("== already-published entry is a no-op")
    reset()
    cid, _ = campaign(["x"])
    publish(cid)
    psql(f"update social_post_entries set status='published' where campaign_id={cid}")
    before = len(stats(skip401=False))
    s, r = publish(cid)
    check(
        "published campaign: 200, status stays published, no request",
        (s, entry(r, "x")["status"], len(stats(skip401=False)) - before),
        (200, "published", 0),
    )

    print("== two concurrent publishes of the same campaign (calls held 3 s in flight)")
    reset()
    publish(campaign(["x"])[0])  # warm a token so both requests skip the 401 refresh
    ctl({"drop_response": {"enabled": True, "delay_seconds": 3}})
    cid, _ = campaign(["instagram", "x"])
    res = []
    th = [threading.Thread(target=lambda: res.append(publish(cid))) for _ in range(2)]
    for t in th:
        t.start()
        time.sleep(0.2)
    for t in th:
        t.join()
    ctl({"drop_response": {"enabled": False}})
    check("both responses 200", sorted(s for s, _ in res), [200, 200])
    for p in ("instagram", "x"):
        k = key_of(cid, p)
        n_req = len(stats(k))
        att = psql(
            f"select attempts from social_post_entries where campaign_id={cid} and platform='{p}'"
        )
        print(f"      {p}: requests sent {n_req}, posts {posts_with(k)}, attempts recorded {att}")
        check(f"{p}: exactly 1 post despite concurrent publishes", posts_with(k), 1)
        check(f"{p}: requests sent == attempts recorded", str(n_req), att)

    print("== ISSUE-008: 3 concurrent publishes with failure_rate 1.0 share the cap of 5")
    for run in range(2):
        reset()
        publish(campaign(["x"])[0])  # warm the token
        ctl({"failure_rate": 1.0})
        cid, _ = campaign(["instagram", "x"])
        res = []
        th = [
            threading.Thread(target=lambda res=res, cid=cid: res.append(publish(cid)))
            for _ in range(3)
        ]
        for t in th:
            t.start()
            time.sleep(0.05)
        for t in th:
            t.join()
        ctl({"failure_rate": 0.0})
        check(f"run {run}: all 3 responses 200", sorted(s for s, _ in res), [200, 200, 200])
        for p in ("instagram", "x"):
            k = key_of(cid, p)
            n_req = len(stats(k))
            row = psql(
                f"select status||'|'||attempts from social_post_entries where campaign_id={cid} and platform='{p}'"
            )
            print(f"      run {run} {p}: requests {n_req}, row {row}")
            check(f"run {run} {p}: requests == attempts == 5", (n_req, row.split("|")[1]), (5, "5"))
            check(f"run {run} {p}: 0 posts", posts_with(k), 0)
            if row.split("|")[0] == "publishing":
                # backend's documented race: the next publish must settle it as failed, no send
                before = len(stats(skip401=False))
                publish(cid)
                row = psql(
                    f"select status||'|'||attempts from social_post_entries where campaign_id={cid} and platform='{p}'"
                )
                check(
                    f"run {run} {p}: racing 'publishing' settled by next publish, no request",
                    (row, len(stats(skip401=False)) - before),
                    ("failed|5", 0),
                )
            else:
                check(f"run {run} {p}: status failed", row, "failed|5")

        print(
            "== exhausted entry: stays failed, sends nothing on later publishes (platform healthy)"
        )
        before = len(stats(skip401=False))
        for _ in range(2):
            s, r = publish(cid)
        rows = [
            psql(
                f"select status||'|'||attempts||'|'||coalesce(platform_post_id,'NULL') "
                f"from social_post_entries where campaign_id={cid} and platform='{p}'"
            )
            for p in ("instagram", "x")
        ]
        check(
            f"run {run}: 2 later publishes 200, rows unchanged",
            (s, rows),
            (200, ["failed|5|NULL"] * 2),
        )
        check(
            f"run {run}: no request sent by later publishes", len(stats(skip401=False)) - before, 0
        )


if __name__ == "__main__":
    try:
        for f in (probe1, probe2, probe6, edges):
            f()
    finally:
        reset()
    print(f"CHECKS FAILED: {len(FAILS)}")
    for n in FAILS:
        print(f"  - {n}")
    sys.exit(1 if FAILS else 0)
