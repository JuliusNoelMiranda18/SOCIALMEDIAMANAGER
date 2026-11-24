# Stage 1 — Fake platform server

**Status:** AWAITING_APPROVAL · **Loops used:** 2/3 · **Date:** 2026-11-24

## Built
- `POST /oauth/token`, `POST /v1/posts` (Bearer + required `Idempotency-Key`, same key replays the stored response), `GET /_posts`
- `GET/POST /_control` (partial, nested merge) and `POST /_control/reset` with switches: `rate_limit` (429 + `Retry-After`), `failure_rate` (503), `drop_response` (store, then delay so the client times out), `forged_signature`, `webhook_url`
- HMAC-SHA256 signed delivery callback (`X-Timestamp`, `X-Signature`, signed over `<ts>.<body>`); `sign()` lives in `fake_platform/signing.py` for Stage 5 to reuse
- `scripts/probes/fake_platform.sh` + `make probe`; `make lint` now also checks formatting
- Vault: [[Fake Platform]] module note, [[API]] updated

## Tester evidence
| Check | Result | Evidence |
|---|---|---|
| Same key twice → 1 post (also 10 concurrent) | PASS | identical 201s, `/_posts` has 1 |
| 429 mode returns `Retry-After` | PASS | `retry-after: 9`, nothing stored |
| Drop mode: timeout, post exists, retry safe | PASS | curl exit 28, still 1 post |
| Callback signature valid / forged invalid | PASS | tester's own HMAC recompute |
| `failure_rate` 1.0 stores nothing | PASS | 3 of 3 → 503, 0 posts |
| No 500s on bad input (NaN, Infinity, bad JSON, bad grant_type, unknown route) | PASS | 422 / 400 / 404 |
| `ruff check` + `ruff format --check` | PASS | All checks passed, 26 files formatted |
| `make test` / `make probe` | PASS | 16 passed / all PASS, exit 0 |
| Secret grep | PASS | only docs quoting the command |

Full output: [[Current Handoff]] (Tester, Iteration 1 and 2).

## Your manual test (do this before /approve 1)
1. `cd /Users/jouleused/Desktop/SOCIALMEDIAMANAGER && docker compose up -d --build --wait`
2. `bash scripts/probes/fake_platform.sh` and read the output. Every line should be `PASS`, and it should end by resetting state.
3. Try a switch by hand, e.g. `curl -X POST localhost:9000/_control -H 'content-type: application/json' -d '{"rate_limit":{"enabled":true,"retry_after_seconds":5}}'`, then post to `/v1/posts` (see the probe for the token and headers). Reset with `curl -X POST localhost:9000/_control/reset`.
4. Browse http://localhost:9000/docs.

## Known limitations
- State is in memory: restarting fake-platform clears posts and tokens.
- The callback goes to `http://api:8000/webhook/social-delivery`, which doesn't exist until Stage 5, so callbacks currently log a warning. Their signatures are verified by tests only, not end to end.
- Tokens never expire; `expires_in` is cosmetic.
- Same key with a different body replays the first response (as designed).
- 422 bodies no longer include `input`/`ctx` on any fake-platform endpoint.

## Issues closed / still open
- Closed: ISSUE-002 (format not in lint), ISSUE-003 (NaN/Infinity → 500). Open: none.

## Dead ends logged
None. (Note: `allow_inf_nan=False` alone was not enough, see BUILDLOG.)

## Next stage preview
Stage 2: data model (posts, campaigns, social_post_entries, tokens, jobs, webhook_events, llm_calls), image pipeline and caption composer with an LLM wrapper and template fallback.

## Approval
_Approved by user on <date>_
