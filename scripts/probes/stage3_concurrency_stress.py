# ruff: noqa: E501, E702
"""Stage 3 tester: concurrent publishes of one campaign, hunting inconsistent entry states (ISSUE-008/009).
    python3 scripts/probes/stage3_concurrency_stress.py RATE CONC N [PRESET_ATTEMPTS]
e.g. `... 0.5 8 25 3` (entries already failed with 3 attempts, 8 concurrent publishes, 25 campaigns).
PRESET simulates a prior publish that ended failed with that many attempts.

Invariant per entry (Senior, iteration 3):
  logged requests <= attempts - preset, attempts <= 5 (PUBLISH_MAX_ATTEMPTS)
  at most 1 post per key; an entry with a post id has exactly 1 post, is not 'failed' and has no last_error
  no entry is 'publishing' without a post id once all requests return, nor after a settling publish
  the settling publish (healthy platform) sends nothing for failed or accepted entries
An attempt counted but never logged by the platform (connection dropped before the server handled it,
e.g. RemoteProtocolError on a reused keep-alive connection) is NOT an anomaly: it is counted and
reported separately as a transport gap. Exit 1 on any anomaly.
"""

import sys
import threading
from collections import Counter

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import stage3_tester as T

rate = float(sys.argv[1])
conc = int(sys.argv[2])
n = int(sys.argv[3])
preset = sys.argv[4] if len(sys.argv) > 4 else None
base = int(preset or 0)
MAX = 5
T.reset()
T.publish(T.campaign(["x"])[0])
T.ctl({"failure_rate": rate})
bad, gaps, errs, outcomes, done = [], [], Counter(), Counter(), []


def row_of(cid, p):
    r = T.psql(
        f"select status||'|'||attempts||'|'||coalesce(platform_post_id,'NULL')||'|'||coalesce(last_error,'NULL') from social_post_entries where campaign_id={cid} and platform='{p}'"
    )
    return r, r.split("|", 3)


for _i in range(n):
    cid, _ = T.campaign(["instagram", "x"])
    if preset:
        T.psql(
            f"update social_post_entries set attempts={preset}, status='failed', idempotency_key=encode(sha256(('{cid}:'||id)::bytea),'hex') where campaign_id={cid}"
        )
    res = []
    th = [
        threading.Thread(target=lambda res=res, cid=cid: res.append(T.publish(cid)[0]))
        for _ in range(conc)
    ]
    [t.start() for t in th]
    [t.join() for t in th]
    for p in ("instagram", "x"):
        k = T.key_of(cid, p)
        row, (st, att, pid, err) = row_of(cid, p)
        nreq = len(T.stats(k))
        posts = T.posts_with(k)
        att = int(att)
        flags = []
        if any(s >= 500 for s in res) or len(res) != conc:
            flags.append(f"http{sorted(set(res))}")
        if att > MAX:
            flags.append("attempts>5")
        if nreq > att - base:
            flags.append(f"req{nreq}>att{att}-{base}")
        if posts > 1:
            flags.append("dup")
        if pid != "NULL" and posts != 1:
            flags.append(f"id-but-{posts}-posts")
        if st == "publishing" and pid == "NULL":
            flags.append("publishing-no-id")
        if st == "failed" and pid != "NULL":
            flags.append("failed-with-id")
        if pid != "NULL" and err != "NULL":
            flags.append("id-with-error")
        if nreq < att - base:
            gaps.append((cid, p, row, nreq, att - base))
        if err != "NULL":
            errs[err] += 1
        outcomes["accepted" if pid != "NULL" else st] += 1
        if flags:
            bad.append((cid, p, row, nreq, posts, flags))
        done.append((cid, p, k, row, nreq))

# settling publish against a healthy platform
T.ctl({"failure_rate": 0.0})
for cid in sorted({d[0] for d in done}):
    s, _ = T.publish(cid)
    if s != 200:
        bad.append((cid, "*", "settle", s, 0, [f"settle-http{s}"]))
for cid, p, k, before, nreq in done:
    row, (st, att, pid, err) = row_of(cid, p)
    flags = []
    if st == "publishing" and pid == "NULL":
        flags.append("settle:stuck-publishing-no-id")
    if st == "failed" and pid != "NULL":
        flags.append("settle:failed-with-id")
    if pid != "NULL" and err != "NULL":
        flags.append("settle:id-with-error")
    st0, _, pid0, _ = before.split("|", 3)
    if (st0 == "failed" or pid0 != "NULL") and (row != before or len(T.stats(k)) != nreq):
        flags.append(f"settle:changed {before} -> {row}")
    if flags:
        bad.append((cid, p, row, len(T.stats(k)), T.posts_with(k), flags))

print(f"rate={rate} conc={conc} n={n} preset={preset} anomalies={len(bad)}")
print(f"  outcomes={dict(outcomes)} last_errors={dict(errs)}")
print(f"  transport_gaps={len(gaps)} (attempt counted, request never logged by the platform)")
for g in gaps:
    print("   gap", g)
for b in bad:
    print("  ", b)
T.reset()
sys.exit(1 if bad else 0)
