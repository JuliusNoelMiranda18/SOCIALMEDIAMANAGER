#!/usr/bin/env bash
# Stage 3 probe 6: no plaintext token in a DB dump or api/worker logs; ciphertext present and unique.
cd "$(dirname "$0")/../.." && . scripts/probes/_stage3_lib.sh
curl -s -X POST "$F/_control/reset" >/dev/null  # invalidates stored tokens -> forces a 401 refresh
C=$(campaign '["instagram","x"]')
check "publish accepted" "$(publish "$C" | jget "sorted(bool(e['platform_post_id']) for e in d['entries'])")" "[True, True]"

TOKENS=$(curl -s "$F/_tokens" | jget "'\n'.join(d)")
check "tokens issued (one per platform)" "$(echo "$TOKENS" | grep -c .)" 2
DUMP=$(docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"')
LOGS=$(docker compose logs api worker 2>&1)
check "dump is non-trivial" "$(echo "$DUMP" | grep -c 'COPY public.platform_tokens')" 1
LEAKS=0
for T in $TOKENS; do
  echo "$DUMP" | grep -qF -- "$T" && { echo "      token found in pg_dump"; LEAKS=1; }
  echo "$LOGS" | grep -qF -- "$T" && { echo "      token found in logs"; LEAKS=1; }
done
check "no plaintext token in pg_dump or api/worker logs" "$LEAKS" 0
check "Authorization header never logged" "$(echo "$LOGS" | grep -ci 'bearer')" 0
check "2 encrypted rows, 12-byte nonces" "$(psql "select count(*) from platform_tokens where length(nonce)=12 and length(ciphertext)>16")" 2
check "ciphertexts differ" "$(psql "select count(distinct ciphertext) from platform_tokens")" 2
check "nonces differ" "$(psql "select count(distinct nonce) from platform_tokens")" 2
finish
