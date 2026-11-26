# Webhook

**Purpose:** Receives the fake platform's signed delivery callback and is the only path that marks an entry `published` (or `failed` on a platform-reported failure). Verify first, then dedupe by `event_id`, then apply, per [[ADR-002 Publish flow]].
**Files:** `app/services/webhooks.py`, `app/repos/webhooks.py`, `app/repos/campaigns.py` (`apply_delivery`, `mark_accepted`), route in `app/api/routes.py`, `migrations/versions/0004_webhooks.py`
**Last changed:** Stage 5 iteration 2, 2026-11-26 (ISSUE-010 advisory lock)

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `social_delivery` | `POST /webhook/social-delivery` | reads the **raw** body, runs `handle` in the threadpool; `InvalidInput` → 400 `{detail: <reason>}`; else 200 `{result}` |
| `sign` | `(secret, timestamp: str, raw: bytes) -> str` | hex HMAC-SHA256 over `b"<ts>.<raw>"`; same scheme as `fake_platform/signing.py` (copied, so the app never imports the fake platform) |
| `verify` | `(raw, timestamp, signature, *, secret, now, tolerance) -> DeliveryEvent` | pure. In order: both headers present; `X-Timestamp` matches `[0-9]{1,12}`; `abs(now - ts) <= tolerance`; `hmac.compare_digest`; only then parse JSON (`DeliveryEvent`); body `timestamp` == header. Raises `InvalidInput(reason)` |
| `DeliveryEvent` | Pydantic model | `event_id` strict str 1..200, `post_id` strict non-empty str, `status` `delivered`\|`failed`, `timestamp` strict int; no NUL in strings (Postgres text); extra fields (`platform`) ignored |
| `handle` | `(session, raw, ts, sig) -> 'applied'\|'unmatched'\|'duplicate'` | rejection → one log line `webhook rejected: <reason>`, no DB write. Else `store`; no row → rollback, `duplicate`; else `apply_delivery` and one commit |
| `repos.webhooks.store` | `(session, event_id, raw_body, platform_post_id, status) -> bool` | `INSERT … ON CONFLICT (event_id) DO NOTHING RETURNING id`; `signature_valid` always true |
| `repos.campaigns.apply_delivery` | `(session, platform_post_id, status) -> bool` | `delivered` → `published`; `failed` → `failed`, `last_error='platform reported failure'`; both `WHERE platform_post_id=:pid AND status='publishing'` |

## Connections
- Depends on: [[Data Model]] (`webhook_events`, `social_post_entries`), [[Api Layer]] (`Settings.webhook_secret`, `webhook_tolerance_seconds`, `InvalidInput`)
- Used by: [[Fake Platform]] (`send_callback`), [[Publishing Service]] (`mark_accepted` reads stored events) · map: [[System Map]] · contract: [[API]]

## Invariants
- No DB write before the signature and body are verified; a forged request can never use up a real `event_id`.
- Each `event_id` is processed once (unique constraint, not read-then-write).
- A verified event for an unknown or terminal entry is stored and answered 200 `unmatched`.
- `published` never regresses (see the state machine in [[Publishing Service]]).
- Logs carry the reason only: never the secret or a signature.

## Tests
- `tests/unit/test_webhooks.py` — scheme equals the fake platform's; valid → published; failed → failed; 16 rejection cases (forged, missing headers, non-int / `1_000` ts, stale past/future, modified body, bad JSON, non-UTF-8, bad status, empty / 201-char / NUL event_id, int post_id, body ts ≠ header) → 400, no row, entry unchanged; log has the reason only; duplicate → processed once; event before `mark_accepted` → `published` (and `failed`); `published` survives a failed event and late worker writes; unknown post → `unmatched` + stored; enqueue → `queued`; `hmac.compare_digest` spied
- `scripts/probes/probe4_webhook.sh` (`make probe4`) — live forged / real / own-signed / stale / tampered / failed-on-published

## Gotchas
- The callback is a background task right after the platform's 201 and is never retried, so it can arrive before the worker stores `platform_post_id`. It is then stored as `unmatched`, and `mark_accepted` picks it up (see [[Publishing Service]]).
- Concurrency (ISSUE-010): `store` and `mark_accepted` each run `SELECT pg_advisory_xact_lock(hashtext(platform_post_id))` as the first statement of their transaction, so per post id the second writer waits for the first to commit; under READ COMMITTED its next statement then sees that commit. Released at commit/rollback. Proven by `tests/acceptance/test_stage5_race.py` (both orders).
- After `make env` writes a new `WEBHOOK_SECRET`, both api and fake-platform must be recreated (`make up`).
- The probe reads the secret with `docker compose exec api python -c …` into an env var; never echo it.
