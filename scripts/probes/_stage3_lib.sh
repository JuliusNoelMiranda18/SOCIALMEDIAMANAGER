# Shared helpers for the Stage 3 probes (sourced). Needs `make up`.
B="${API_URL:-http://localhost:8000}"
F="${FAKE_PLATFORM_URL:-http://localhost:9000}"
FAIL=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1 (got '$2', want '$3')"; FAIL=1; fi; }
jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
psql() { docker compose exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' _ "$1"; }
ctl() { curl -s -o /dev/null -X POST "$F/_control" -H 'Content-Type: application/json' -d "$1"; }
# campaign <platforms-json> -> prints the campaign id
campaign() {
  local pid
  pid=$(curl -s -X POST "$B/posts" -H 'Content-Type: application/json' \
    -d '{"title":"Stage 3 probe","body":"We launched a new product today. Come and see."}' | jget "d['id']")
  curl -s -X POST "$B/campaigns" -H 'Content-Type: application/json' \
    -d "{\"post_id\":$pid,\"platforms\":$1}" | jget "d['id']"
}
publish() { curl -s -X POST "$B/campaigns/$1/publish"; }
# posts_for <campaign id> <platform> -> number of fake-platform posts carrying that entry's key
posts_for() {
  local key
  key=$(psql "select idempotency_key from social_post_entries where campaign_id=$1 and platform='$2'")
  curl -s "$F/_posts" | jget "sum(p['idempotency_key']=='$key' for p in d)"
}
finish() { [ $FAIL = 0 ] && echo "ALL PASS" || { echo "PROBE FAILED"; exit 1; }; }
