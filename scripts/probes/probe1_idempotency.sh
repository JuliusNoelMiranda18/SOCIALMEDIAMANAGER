#!/usr/bin/env bash
# Stage 3 probe 1: publish twice, and retry after a dropped response -> exactly 1 post per platform.
cd "$(dirname "$0")/../.." && . scripts/probes/_stage3_lib.sh
curl -s -X POST "$F/_control/reset" >/dev/null

echo "== publish twice"
C=$(campaign '["instagram","x"]')
R=$(publish "$C")
check "both entries accepted" "$(echo "$R" | jget "sorted(bool(e['platform_post_id']) for e in d['entries'])")" "[True, True]"
check "status publishing (webhook marks published)" "$(echo "$R" | jget "{e['status'] for e in d['entries']}")" "{'publishing'}"
R2=$(publish "$C")
check "second publish is a no-op" "$(echo "$R2" | jget "[e['attempts'] for e in d['entries']]")" "[1, 1]"
for P in instagram x; do check "$P: exactly 1 post" "$(posts_for "$C" "$P")" 1; done

echo "== dropped response (drop delay 8 s > PUBLISH_TIMEOUT_SECONDS 5) then retry"
ctl '{"drop_response":{"enabled":true,"delay_seconds":8}}'
C=$(campaign '["instagram","x"]')
OUT=$(mktemp); trap 'rm -f "$OUT"' EXIT
publish "$C" > "$OUT" &
sleep 2  # first request is in flight, waiting on the dropped response
ROW=$(psql "select count(*) from social_post_entries where campaign_id=$C and idempotency_key is not null and status='publishing' and platform_post_id is null")
check "key stored + committed before the call returned" "$([ "$ROW" -ge 1 ] && echo yes)" yes
wait
R=$(cat "$OUT")
ctl '{"drop_response":{"enabled":false}}'
check "both accepted after retry" "$(echo "$R" | jget "sorted(bool(e['platform_post_id']) for e in d['entries'])")" "[True, True]"
check "2 attempts each (timeout, then replay)" "$(echo "$R" | jget "[e['attempts'] for e in d['entries']]")" "[2, 2]"
for P in instagram x; do check "$P: exactly 1 post despite the timeout" "$(posts_for "$C" "$P")" 1; done
check "4 posts in total" "$(curl -s "$F/_posts" | jget "len(d)")" 4
finish
