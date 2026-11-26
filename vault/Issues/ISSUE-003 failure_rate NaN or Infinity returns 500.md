# ISSUE-003 failure_rate NaN or Infinity returns 500

**Status:** closed (stage 1 iteration 2)
**Stage / iteration:** 1 / 1
**Owner:** backend
**Found by:** tester · [[Stage 1]] · [[_Issues Index]]

## Reproduce
```
curl -si -XPOST localhost:9000/_control -H 'Content-Type: application/json' -d '{"failure_rate":NaN}'
curl -si -XPOST localhost:9000/_control -H 'Content-Type: application/json' -d '{"failure_rate":Infinity}'
```

## Expected
422 (invalid control value; handoff: validation errors are 4xx, never 500). State unchanged.

## Actual
`HTTP/1.1 500 Internal Server Error` for both ("ERROR: Exception in ASGI application" in fake-platform logs; probably the 422 error body cannot serialise the non-finite input). State is unchanged.

## Suspected location
`fake_platform/main.py` `ControlUpdate.failure_rate` / `Control.failure_rate` (`Field(..., ge=0, le=1)`). Use `allow_inf_nan=False` on the field (also `retry_after_seconds` is int so unaffected).

## Minor notes (not blocking)
- Nested partial update: `{"rate_limit":{"enabled":false}}` resets `retry_after_seconds` to the default 30 (sub-object is replaced, not merged).
- Same Idempotency-Key with a different body returns the first stored response (201, no new post). Matches the handoff design; real platforms may return 409/422.

## Fix
Iteration 2: `allow_inf_nan=False` on `failure_rate` plus a `RequestValidationError` handler in `fake_platform/main.py` that drops the echoed `input` (it broke JSON encoding). Regression tests added. See [[Fake Platform]].
