#!/usr/bin/env bash
# Drives the live fake platform with curl. Usage: bash scripts/probes/fake_platform.sh
B="${FAKE_PLATFORM_URL:-http://localhost:9000}"
FAIL=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1 (got '$2', want '$3')"; FAIL=1; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
ctl() { curl -s -o /dev/null -X POST "$B/_control" -H 'Content-Type: application/json' -d "$1"; }
count() { curl -s "$B/_posts" | grep -o '"idempotency_key"' | wc -l | tr -d ' '; }
P='{"platform":"instagram","caption":"hello","image_url":null}'
post() { curl -s "$@" -X POST "$B/v1/posts" -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d "$P"; }

curl -s -X POST "$B/_control/reset" >/dev/null
echo "== token"
T=$(curl -s -X POST "$B/oauth/token" -d grant_type=client_credentials -d client_id=a -d client_secret=b \
  | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
check "token issued" "$([ -n "$T" ] && echo yes)" yes
check "bad grant_type -> 400" "$(code -X POST "$B/oauth/token" -d grant_type=password)" 400
echo "== post + idempotency"
check "no auth -> 401" "$(code -X POST "$B/v1/posts" -H 'Content-Type: application/json' -H 'Idempotency-Key: k' -d "$P")" 401
check "missing key -> 400" "$(code -X POST "$B/v1/posts" -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d "$P")" 400
R1=$(post -H 'Idempotency-Key: k1'); R2=$(post -H 'Idempotency-Key: k1')
check "post accepted" "$(echo "$R1" | grep -c '"accepted"')" 1
check "same key -> identical response" "$R1" "$R2"
check "same key -> 1 stored post" "$(count)" 1
echo "== 429 mode"
ctl '{"rate_limit":{"enabled":true,"retry_after_seconds":7}}'
H=$(curl -si -X POST "$B/v1/posts" -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: k2' -d "$P" | tr -d '\r')
check "429 status" "$(echo "$H" | head -1 | cut -d' ' -f2)" 429
check "Retry-After: 7" "$(echo "$H" | grep -i '^retry-after:' | cut -d' ' -f2)" 7
check "429 stored nothing" "$(count)" 1
ctl '{"rate_limit":{"enabled":false}}'
echo "== failure mode"
ctl '{"failure_rate":1.0}'
check "failure -> 503" "$(code -X POST "$B/v1/posts" -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -H 'Idempotency-Key: k3' -d "$P")" 503
check "503 stored nothing" "$(count)" 1
ctl '{"failure_rate":0}'
echo "== drop mode"
ctl '{"drop_response":{"enabled":true,"delay_seconds":5}}'
post -m 2 -H 'Idempotency-Key: k4' >/dev/null; RC=$?
check "client timed out (curl exit 28)" "$RC" 28
check "post exists despite timeout" "$(count)" 2
check "retry same key returns stored" "$(post -m 2 -H 'Idempotency-Key: k4' | grep -c '"accepted"')" 1
check "retry made no second post" "$(count)" 2
ctl '{"drop_response":{"enabled":false}}'
echo "== forged mode"
ctl '{"forged_signature":true}'
check "forged flag on" "$(curl -s "$B/_control" | grep -c '"forged_signature":true')" 1
check "post still accepted" "$(code -X POST "$B/v1/posts" -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -H 'Idempotency-Key: k5' -d "$P")" 201
echo "== bad control value"
check "failure_rate 2 -> 422" "$(code -X POST "$B/_control" -H 'Content-Type: application/json' -d '{"failure_rate":2}')" 422
echo "== GET /_posts"
check "3 posts stored" "$(count)" 3
curl -s -X POST "$B/_control/reset" >/dev/null
check "reset clears posts" "$(count)" 0
exit $FAIL
