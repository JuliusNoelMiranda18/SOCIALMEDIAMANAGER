# ISSUE-007 2xx without id or bad token body returns 500

**Status:** closed (Stage 3 iteration 2)
**Stage / iteration:** 3 / 1
**Owner:** backend
**Found by:** tester · [[Stage 3]] · [[Publisher Adapters]] · [[_Issues Index]]

## Reproduce
The fake platform has no switch for this, so the probe swaps the api's shared httpx client for an `httpx.MockTransport` (no app code edited):
```
docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py ; echo exit=$?
```

## Expected
A malformed platform reply becomes a typed `PublishOutcome` (for example `retryable` "2xx without id", or `fatal`), recorded in `attempts`/`last_error`. The endpoint returns 200 with the entry. Never a 500.

## Actual
```
FAIL  201 {} (no id): HTTP 500 entry=None
FAIL  201 non-JSON body: HTTP 500 entry=None
FAIL  token 200 without access_token: HTTP 500 entry=None
FAIL  token 200 non-JSON: HTTP 500 entry=None
exit=1
direct call: FakeXPublisher(...).publish(...) -> raises KeyError 'id'
```
Afterwards each entry is stuck at `status=publishing, attempts=0, platform_post_id=NULL`. For the "201 without id" case the platform has accepted the post, but the app never records it. Every later publish replays the same key and gets the same stored body, so it raises the same 500 every time.

## Suspected location
- `app/publishers/fake.py` `_send`: `r.json()["id"]` is outside the `try` and has no `KeyError`/`ValueError` handling.
- `app/publishers/tokens.py` `get_token`: `r.json()["access_token"]` has the same problem. This is called from inside `_send`'s `try`, but only `httpx.HTTPError` is caught.
See [[Publisher Adapters]], [[Token Crypto]].

## Resolution
`_send` maps a 2xx that is not JSON or has no non-empty string `id` to `retryable("malformed response")`; `get_token` raises `BadTokenResponse` for a token reply without a string `access_token`, which `_send` maps to `retryable("bad token response")` ([[Publisher Adapters]]). `publish_campaign` also has a last-resort guard: an unexpected exception marks that entry `failed` with the exception type and moves on ([[Publishing Service]]). Proof: `test_malformed_2xx_is_retryable`, `test_bad_token_response_is_retryable`, `test_malformed_2xx_ends_failed_with_reason`, `test_unexpected_error_fails_one_entry_and_continues`; `stage3_bad_2xx.py` → 4× PASS, HTTP 200, `('failed', 5, <reason>)`.
