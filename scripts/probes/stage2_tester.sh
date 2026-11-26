#!/usr/bin/env bash
# Stage 2 tester probe (regression suite). Needs the live stack: `make up`.
#   bash scripts/probes/stage2_tester.sh
# Runs: live content checks, 4xx matrix, host ./media check, column types, atomicity.
cd "$(dirname "$0")/../.." || exit 1
FAIL=0
psql() { docker compose exec -T db sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' _ "$1"; }
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1 (got '$2', want '$3')"; FAIL=1; fi; }

echo "== live content checks"
OUT=$(docker compose exec -T api python -I - < scripts/probes/stage2_checks.py) || FAIL=1
echo "$OUT" | grep -v '^MEDIA'
echo "== host ./media files"
for f in $(echo "$OUT" | sed -n 's/^MEDIA \(.*png\)$/\1/p'); do
  check "host media/$f exists" "$([ -s "media/$f" ] && echo yes)" yes
done

echo "== caption fuzz (ISSUE-004)"
docker compose exec -T api python -I - < scripts/probes/stage2_caption_fuzz.py || FAIL=1

echo "== 4xx matrix"
docker compose exec -T api python -I - < scripts/probes/stage2_4xx.py | grep -E '^FAIL|^SKIP|CHECKS'
[ "${PIPESTATUS[0]}" = 0 ] || FAIL=1

echo "== body cap via curl (8 MB)"
BIG=$(mktemp)
head -c $((9*1024*1024)) /dev/zero | tr '\0' a > "$BIG"
check "curl 9 MB Content-Length -> 413" "$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/posts -H 'Content-Type: application/json' --data-binary @"$BIG")" 413
check "curl 9 MB chunked -> 413" "$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/posts -H 'Content-Type: application/json' -H 'Transfer-Encoding: chunked' --data-binary @"$BIG")" 413
check "curl non-numeric Content-Length -> 4xx" "$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/posts -H 'Content-Type: application/json' -H 'Content-Length: abc' --data-binary '{}' | cut -c1)" 4
rm -f "$BIG"

echo "== column types"
TYPES=$(psql "select column_name||':'||data_type from information_schema.columns where table_name='llm_calls' and column_name in ('prompt_tokens','completion_tokens','cost_micro_usd','latency_ms') order by column_name" | tr '\n' ' ')
check "llm_calls int columns" "$TYPES" "completion_tokens:integer cost_micro_usd:integer latency_ms:integer prompt_tokens:integer "
IDS=$(psql "select string_agg(table_name||'.'||data_type, ' ' order by table_name) from information_schema.columns where column_name='id' and table_schema='public'")
check "all ids bigint" "$(echo "$IDS" | tr ' ' '\n' | grep -vc 'bigint$')" 0

echo "== atomicity: x image write fails after instagram image was written"
PID=$(curl -s -X POST localhost:8000/posts -H 'Content-Type: application/json' -d '{"title":"Atomic","body":"One. Two."}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
NEXT=$(psql "select case when is_called then last_value+1 else last_value end from campaigns_id_seq")
COUNTS="select (select count(*) from campaigns)||'/'||(select count(*) from social_post_entries)||'/'||(select count(*) from llm_calls)"
BEFORE=$(psql "$COUNTS")
# Non-invasive fault: the x target path is a symlink into a non-existent dir, so PNG save fails.
ln -s /proc/nonexistent/dir/x.png "media/${NEXT}_x.png"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/campaigns -H 'Content-Type: application/json' \
  -d "{\"post_id\":$PID,\"platforms\":[\"instagram\",\"x\"]}")
check "forced render failure -> 500" "$CODE" 500
check "no new campaign/entry/llm_calls rows" "$(psql "$COUNTS")" "$BEFORE"
check "no orphan ${NEXT}_instagram.png" "$([ -e "media/${NEXT}_instagram.png" ] && echo present || echo absent)" absent
check "fault symlink removed by cleanup" "$([ -L "media/${NEXT}_x.png" ] && echo present || echo absent)" absent
rm -f "media/${NEXT}_x.png"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/campaigns -H 'Content-Type: application/json' \
  -d "{\"post_id\":$PID,\"platforms\":[\"instagram\",\"x\"]}")
check "same request succeeds after fault removed" "$CODE" 201

[ $FAIL = 0 ] && echo "ALL PASS" || { echo "PROBE FAILED"; exit 1; }
