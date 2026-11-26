#!/usr/bin/env bash
# Stage 4 probe 3: kill the worker mid-publish; after restart + lease expiry every job finishes
# and each entry has exactly one post on the fake platform.
cd "$(dirname "$0")/../.." && . scripts/probes/_stage3_lib.sh
curl -s -X POST "$F/_control/reset" >/dev/null
ctl '{"latency_ms":1500}'
trap 'ctl "{\"latency_ms\":0}"' EXIT

AT=$(python3 -c "from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat())")
CIDS=() JOBS=()
for i in 1 2 3 4; do
  C=$(campaign '["instagram","x"]')
  R=$(curl -s -X POST "$B/campaigns/$C/schedule" -H 'Content-Type: application/json' -d "{\"run_at\":\"$AT\"}")
  CIDS+=("$C"); JOBS+=("$(echo "$R" | jget "d['id']")")
done
check "4 jobs scheduled, all pending" "$(for J in "${JOBS[@]}"; do curl -s "$B/jobs/$J" | jget "d['status']"; done | sort -u)" pending
[ $FAIL = 0 ] || finish  # nothing scheduled: the rest would only time out
echo "== advance-time 60 -> jobs due"
curl -s -X POST "$B/_dev/advance-time" -H 'Content-Type: application/json' -d '{"seconds":60}'; echo

N=0; end=$((SECONDS + 60))
while [ $SECONDS -lt $end ]; do
  N=$(curl -s "$F/_posts" | jget "len(d)")
  [ "$N" -ge 1 ] && break
  sleep 0.1
done
docker compose kill worker >/dev/null 2>&1
echo "      killed the worker with $N post(s) on the fake platform"
check "killed mid-run (1..7 posts)" "$([ "$N" -ge 1 ] && [ "$N" -lt 8 ] && echo yes)" yes
RUNNING=$(psql "select count(*) from jobs where status='running'")
check "at least one job still running (orphaned)" "$([ "$RUNNING" -ge 1 ] && echo yes)" yes

docker compose up -d worker >/dev/null 2>&1
echo "== advance-time 60 (> JOB_LEASE_SECONDS) -> orphaned lease expires"
curl -s -X POST "$B/_dev/advance-time" -H 'Content-Type: application/json' -d '{"seconds":60}'; echo
for J in "${JOBS[@]}"; do check "job $J done" "$(job_wait "$J" 120)" done; done

for C in "${CIDS[@]}"; do
  check "campaign $C: both entries have a platform_post_id" \
    "$(curl -s "$B/campaigns/$C" | jget "all(e['platform_post_id'] for e in d['entries'])")" True
  for P in instagram x; do check "campaign $C $P: exactly 1 post" "$(posts_for "$C" "$P")" 1; done
done
check "8 posts in total" "$(curl -s "$F/_posts" | jget "len(d)")" 8
echo "      worker log (claims/outcomes):"
docker compose logs --no-log-prefix worker 2>&1 | grep -E "job [0-9]+" | tail -12 | sed 's/^/        /'
finish
