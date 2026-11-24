# Api Layer

**Purpose:** HTTP entrypoint plus settings and the idle worker; Stage 0 only exposes `/health`.
**Files:** `app/main.py`, `app/config.py`, `app/worker/__main__.py`, `app/api/`, `app/services/`, `app/repos/` (empty packages)
**Last changed:** Stage 0, 2026-11-24

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `health` | `GET /health -> {"status":"ok"}` | liveness for compose healthcheck |
| `Settings` | pydantic-settings class | reads DATABASE_URL, FAKE_PLATFORM_URL, TOKEN_ENCRYPTION_KEY, WEBHOOK_SECRET from env |
| worker loop | `python -m app.worker` | logs "worker idle" every 5s; job claiming is Stage 4 |

## Connections
- Depends on: Postgres (via `DATABASE_URL`, migrations only for now)
- Used by: [[System Map]] (HTTP layer box), [[API]]

## Invariants
Layers: api -> services -> repos -> adapters. Secrets from env only.

## Tests
- `tests/test_health.py` — `/health` on the API and the fake platform

## Gotchas
Placeholder secrets in `.env.example` are not real; real key handling lands in Stages 3 and 5.
