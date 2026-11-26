#!/usr/bin/env bash
# Stage 2 probe: post -> campaign -> images + captions + llm_calls. Needs `make up`.
B="${API_URL:-http://localhost:8000}"
FAIL=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1 (got '$2', want '$3')"; FAIL=1; fi; }
jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
dims() { docker compose exec -T api python -I -c "import sys; from PIL import Image; i=Image.open(sys.stdin.buffer); print(i.format, i.width, i.height)"; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
psql() { docker compose exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' _ "$1"; }

BEFORE=$(psql "select count(*) from llm_calls")
PID=$(curl -s -X POST "$B/posts" -H 'Content-Type: application/json' \
  -d '{"title":"Spring Sale Launch","body":"We launched a new product today. It is fast and cheap! Come and see."}' | jget "d['id']")
check "post created" "$([ -n "$PID" ] && echo yes)" yes
R=$(curl -s -X POST "$B/campaigns" -H 'Content-Type: application/json' \
  -d "{\"post_id\":$PID,\"platforms\":[\"instagram\",\"x\"],\"brand_name\":\"Acme\"}")
check "2 entries" "$(echo "$R" | jget "len(d['entries'])")" 2
for P in instagram x; do
  U=$(echo "$R" | jget "[e for e in d['entries'] if e['platform']=='$P'][0]['image_url']")
  CT=$(curl -s -o "$T/$P.png" -w '%{http_code} %{content_type}' "$B$U")
  check "$P image served" "$CT" "200 image/png"
  WANT=$([ $P = x ] && echo "PNG 1600 900" || echo "PNG 1080 1080")
  check "$P image dimensions" "$(dims < "$T/$P.png")" "$WANT"
done
check "captions differ" "$(echo "$R" | jget "d['entries'][0]['caption'] != d['entries'][1]['caption']")" True
check "llm_calls +2" "$(( $(psql "select count(*) from llm_calls") - BEFORE ))" 2
check "bad input -> 422" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/posts" -H 'Content-Type: application/json' -d '{"title":""}')" 422
[ $FAIL = 0 ] && echo "ALL PASS" || { echo "PROBE FAILED"; exit 1; }
