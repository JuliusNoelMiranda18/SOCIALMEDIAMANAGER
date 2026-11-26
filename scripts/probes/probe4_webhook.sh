#!/usr/bin/env bash
# Stage 5 probe 4: only a verified, fresh, unmodified callback marks an entry published; once.
cd "$(dirname "$0")/../.." && . scripts/probes/_stage3_lib.sh
# The secret stays in this process's environment; it is never printed.
WEBHOOK_SECRET=$(docker compose exec -T api python -c "from app.config import settings; print(settings.webhook_secret)")
export WEBHOOK_SECRET
# send_event <post id> <status> <event id> <ts offset s> [tamper] -> "<http code> <body>"
send_event() {
  python3 - "$@" <<'PY'
import hashlib, hmac, json, os, sys, time, urllib.error, urllib.request
pid, status, event_id, offset = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
ts = int(time.time()) + offset
raw = json.dumps({"event_id": event_id, "post_id": pid, "status": status, "timestamp": ts}).encode()
sig = hmac.new(os.environ["WEBHOOK_SECRET"].encode(), str(ts).encode() + b"." + raw, hashlib.sha256).hexdigest()
if len(sys.argv) > 5:
    raw = raw[:-2] + bytes([raw[-2] ^ 1]) + raw[-1:]  # flip one bit of one byte after signing
req = urllib.request.Request(os.environ.get("API_URL", "http://localhost:8000") + "/webhook/social-delivery",
    raw, {"Content-Type": "application/json", "X-Timestamp": str(ts), "X-Signature": sig}, method="POST")
try:
    with urllib.request.urlopen(req) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
PY
}
statuses() { curl -s "$B/campaigns/$1" | jget "sorted({e['status'] for e in d['entries']})"; }
EVENTS() { psql "select count(*) from webhook_events"; }
curl -s -X POST "$F/_control/reset" >/dev/null

echo "== (a) forged signatures are rejected"
ctl '{"forged_signature":true}'
N0=$(EVENTS)
C=$(campaign '["instagram","x"]')
R=$(publish "$C")
sleep 3  # the forged callbacks have arrived and been rejected
check "both accepted with a post id" "$(echo "$R" | jget "sorted(bool(e['platform_post_id']) for e in d['entries'])")" "[True, True]"
check "both still publishing" "$(statuses "$C")" "['publishing']"
check "no webhook_events row added" "$(EVENTS)" "$N0"

echo "== (b) real signatures publish"
ctl '{"forged_signature":false}'
C2=$(campaign '["instagram","x"]')
publish "$C2" >/dev/null
end=$((SECONDS + 15)); while [ $SECONDS -lt $end ] && [ "$(statuses "$C2")" != "['published']" ]; do sleep 0.5; done
check "both published within 15 s" "$(statuses "$C2")" "['published']"

echo "== (c) own signed event: applied, then duplicate"
PID=$(psql "select platform_post_id from social_post_entries where campaign_id=$C and platform='x'")
EV="probe4-$(date +%s)-$$"
check "first POST applied" "$(send_event "$PID" delivered "$EV" 0)" '200 {"result":"applied"}'
check "second POST duplicate" "$(send_event "$PID" delivered "$EV" 0)" '200 {"result":"duplicate"}'
check "one webhook_events row" "$(psql "select count(*) from webhook_events where event_id='$EV'")" 1
check "entry published" "$(psql "select status from social_post_entries where platform_post_id='$PID'")" published

echo "== (d) stale timestamp, (e) modified body"
PID2=$(psql "select platform_post_id from social_post_entries where campaign_id=$C and platform='instagram'")
check "timestamp now-600 -> 400" "$(send_event "$PID2" delivered "$EV-d" -600 | cut -c1-3)" 400
check "one byte changed after signing -> 400" "$(send_event "$PID2" delivered "$EV-e" 0 tamper | cut -c1-3)" 400
check "rejected events not stored" "$(psql "select count(*) from webhook_events where event_id like '$EV-%'")" 0
check "entry still publishing" "$(psql "select status from social_post_entries where platform_post_id='$PID2'")" publishing

echo "== (f) failed event never regresses published"
check "failed event on published entry: unmatched" "$(send_event "$PID" failed "$EV-f" 0)" '200 {"result":"unmatched"}'
check "entry stays published" "$(psql "select status from social_post_entries where platform_post_id='$PID'")" published
finish
