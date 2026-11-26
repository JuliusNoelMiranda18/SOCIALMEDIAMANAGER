# Fake Platform

**Purpose:** In-memory simulator of Instagram/X publishing, with switches to force 429, 503, dropped responses and forged webhook signatures.
**Files:** `fake_platform/main.py`, `fake_platform/signing.py`
**Last changed:** Stage 1, 2026-11-24

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `create_post` | `POST /v1/posts` | auth, then idempotency replay, rate limit, failure rate, accept, schedule callback, optional delay |
| `token` | `POST /oauth/token` | form body parsed by hand (no python-multipart); issues Bearer token |
| `Control` / `ControlUpdate` | pydantic | switch state; partial update (nested switches merge field by field), `extra=forbid`, NaN/Infinity rejected with 422 |
| `send_callback` | `(post)` | builds and signs the delivery event, calls `deliver`, swallows errors with a warning |
| `deliver` | `(url, body, headers)` | the one network call; tests monkeypatch it |
| `sign` | `(secret, timestamp, body) -> hex` | HMAC-SHA256 over `"<ts>.<body>"`; Stage 5 reuses it |

## Connections
- Depends on: [[Api Layer]] · map: [[System Map]] · decision: [[ADR-001 Stack]] (`app.config.settings.webhook_secret`)
- Used by: Stage 2+ adapters (via `FAKE_PLATFORM_URL`), Stage 5 webhook receiver

## Invariants
- Check order: auth, idempotency replay, rate limit, failure rate, accept.
- A 429/503 stores nothing and no idempotency record, so a retry with the same key is treated as fresh.
- Replay returns the stored status and body, creates no post, sends no callback.
- Drop mode stores the post and records the key before sleeping.
- A failing callback never affects the post response.

## Tests
- `tests/unit/test_fake_platform.py` — every endpoint and switch, signature verify and forged, unreachable webhook, 422/400/401 paths
- `scripts/probes/fake_platform.sh` (`make probe`) — live curl probe

## Gotchas
- State lives in one process; `/_control/reset` clears posts, keys, tokens and switches.
- Tokens never expire (`expires_in` is cosmetic).
- Drop mode holds the worker connection for `delay_seconds`; the post still exists.
