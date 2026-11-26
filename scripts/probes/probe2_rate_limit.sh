#!/usr/bin/env bash
# Stage 3 probe 2: 429 x2 with Retry-After 2 -> published on the 3rd request, gaps >= 2 s.
cd "$(dirname "$0")/../.." && . scripts/probes/_stage3_lib.sh

for FMT in seconds http-date; do
  echo "== Retry-After as $FMT"
  curl -s -X POST "$F/_control/reset" >/dev/null
  ctl "{\"rate_limit\":{\"enabled\":true,\"retry_after_seconds\":2,\"count\":2,\"format\":\"$FMT\"}}"
  C=$(campaign '["instagram"]')
  R=$(publish "$C")
  check "accepted" "$(echo "$R" | jget "bool(d['entries'][0]['platform_post_id'])")" True
  check "3 attempts" "$(echo "$R" | jget "d['entries'][0]['attempts']")" 3
  # 401s are the token refresh after the reset (same attempt); count the rest
  S=$(curl -s "$F/_stats")
  check "statuses 429, 429, 201" "$(echo "$S" | jget "[r['status'] for r in d['post_requests'] if r['status']!=401]")" "[429, 429, 201]"
  GAPS=$(echo "$S" | jget "(lambda t: [round(b-a,2) for a,b in zip(t,t[1:])])([__import__('datetime').datetime.fromisoformat(r['at']).timestamp() for r in d['post_requests'] if r['status']!=401])")
  echo "      gaps between requests: $GAPS s"
  check "every gap >= 2 s" "$(echo "$GAPS" | python3 -c "import sys,ast; print(all(g>=2 for g in ast.literal_eval(sys.stdin.read())))")" True
  check "exactly 1 post" "$(posts_for "$C" instagram)" 1
done
finish
