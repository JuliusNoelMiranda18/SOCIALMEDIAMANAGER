# ISSUE-006 short nonce in platform_tokens returns 500

**Status:** closed (Stage 3 iteration 2)
**Stage / iteration:** 3 / 1
**Owner:** backend
**Found by:** tester · [[Stage 3]] · [[Token Crypto]] · [[_Issues Index]]

## Reproduce
```
python3 scripts/probes/stage3_tester.py      # section "P6 tamper nonce to a wrong length"
# by hand:
psql: update platform_tokens set nonce = decode('00000000','hex') where platform='x';
curl -X POST localhost:8000/campaigns/<new x campaign>/publish
```

## Expected
A tampered or corrupt token row is treated like any other undecryptable row: fetch a fresh token, replace the row, publish. Never a 500 (handoff: "tamper ... publish handles it, never 500").

## Actual
```
FAIL  short nonce: no 500 (got False, want True)
      status 500 body Internal Server Error
      entry row after the call: publishing|0
api-1 | ValueError: Nonce must be between 8 and 128 bytes
```
Flipping a ciphertext byte, zeroing a 12-byte nonce and truncating the ciphertext to 5 bytes all recover correctly (`InvalidTag`). Only a nonce of the wrong length fails, because `AESGCM.decrypt` raises `ValueError` before the tag check. No token appears in the traceback or logs.

## Suspected location
`app/publishers/tokens.py` `get_token`: `except InvalidTag:` should also catch `ValueError` (or `crypto.decrypt` should map both to one error). Add a unit test with a 4-byte nonce. See [[Token Crypto]].

## Resolution
`get_token` now treats `InvalidTag`, `ValueError` (wrong nonce length) and `TypeError` as "no usable token": it fetches a fresh one and overwrites the row. Fixed in `app/publishers/tokens.py` ([[Token Crypto]]). Proof: `tests/unit/test_publishers.py::test_undecryptable_token_row_fetches_fresh_token` (4-byte nonce, zeroed nonce, short ciphertext, wrong AAD); `stage3_tester.py` → `PASS  short nonce: no 500`.
