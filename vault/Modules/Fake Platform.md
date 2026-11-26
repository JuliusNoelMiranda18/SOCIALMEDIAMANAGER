# Fake Platform

**Purpose:** In-memory simulator of Instagram/X publishing, with switches to force 429, 503, dropped responses and forged webhook signatures.
**Files:** `fake_platform/main.py`, `fake_platform/signing.py`
**Last changed:** Stage 3, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `create_post` | `POST /v1/posts` | auth, then idempotency replay, rate limit, failure rate, accept, schedule callback, optional delay |
| `token` | `POST /oauth/token` | form body parsed by hand (no python-multipart); issues Bearer token |
| `Control` / `ControlUpdate` | pydantic | switch state; partial update (nested switches merge field by field), `extra=forbid`, NaN/Infinity rejected with 422 |
| `record_post_requests` | HTTP middleware | appends `{at, idempotency_key, status}` to `stats` for every `POST /v1/posts` (arrival time; status filled after the response) |
| `get_stats` / `list_tokens` | `GET /_stats`, `GET /_tokens` | probe helpers (Stage 3) |
| `send_callback` | `(post)` | builds and signs the delivery event, calls `deliver`, swallows errors with a warning |
| `deliver` | `(url, body, headers)` | the one network call; tests monkeypatch it |
| `sign` | `(secret, timestamp, body) -> hex` | HMAC-SHA256 over `"<ts>.<body>"`; Stage 5 reuses it |

## Connections
- Depends on: [[Api Layer]] · map: [[System Map]] · decision: [[ADR-001 Stack]] (`app.config.settings.webhook_secret`)
- Used by: [[Publisher Adapters]] (via `FAKE_PLATFORM_URL`), [[Token Crypto]] (`/oauth/token`), Stage 5 webhook receiver

## Invariants
- Check order: auth, idempotency replay, rate limit, failure rate, accept.
- A 429/503 stores nothing and no idempotency record, so a retry with the same key is treated as fresh.
- Replay returns the stored status and body, creates no post, sends no callback.
- Drop mode stores the post and records the key before sleeping.
- A failing callback never affects the post response.
- `rate_limit.count` counts only fresh posts (replays answer first) and turns the switch off when it reaches 0.
- `rate_limit.format: http-date` sends `ceil(now) + retry_after_seconds` so a client honouring it never comes back early.

## Tests
- `tests/unit/test_fake_platform.py` — every endpoint and switch, signature verify and forged, unreachable webhook, 422/400/401 paths
- `scripts/probes/fake_platform.sh` (`make probe`) — live curl probe
- `tests/unit/test_fake_platform.py::test_rate_limit_count_and_http_date`, `::test_stats_and_tokens` — Stage 3 additions

## Gotchas
- State lives in one process; `/_control/reset` clears posts, keys, tokens, stats and switches. Reset also invalidates the api's stored tokens, so the next publish does one 401 + refresh (visible in `/_stats`).
- Tokens never expire (`expires_in` is cosmetic).
- Drop mode holds the worker connection for `delay_seconds`; the post still exists.
