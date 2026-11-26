# Data Model

**Purpose:** SQLAlchemy 2 models for all seven tables, the engine/session, and the single Alembic migration that creates them.
**Files:** `app/models.py`, `app/db.py`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `app/repos/posts.py`, `app/repos/campaigns.py`
**Last changed:** Stage 2, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `Post`, `Campaign`, `SocialPostEntry`, `PlatformToken`, `Job`, `WebhookEvent`, `LlmCall` | declarative models | BIGINT identity ids, integer money/token/latency fields |
| `SocialPostEntry.image_url` | property | `/media/<image_path>` |
| `get_session` | FastAPI dependency | one `Session` per request |
| `repos.posts.add/get`, `repos.campaigns.add/add_entry/get` | `(session, ...)` | flush-only inserts (caller commits); `get` eager-loads entries |
| `0001_initial` | Alembic revision | creates all 7 tables; downgrade drops them |

## Connections
- Depends on: Postgres (`DATABASE_URL`)
- Used by: [[Api Layer]], [[Caption Composer]] (writes `llm_calls`), [[System Map]]

## Invariants
- `UNIQUE(campaign_id, platform)` on `social_post_entries`; `platform_tokens.platform` and `webhook_events.event_id` unique.
- Indexes: `campaigns.post_id`, `llm_calls.entry_id`, `jobs(status, run_at)` for the Stage 4 worker.
- `platform_tokens`, `jobs`, `webhook_events` are tables only until Stages 3/4/5.
- The api container runs `alembic upgrade head` before uvicorn.

## Tests
- `tests/conftest.py` — creates `app_test`, migrates to head, truncates all tables after each test
- `tests/unit/test_api.py` — rows exist after the happy path; nothing saved on failure

## Gotchas
- `migrations/env.py` reads `settings.database_url`, so tests point alembic at `app_test` by setting `DATABASE_URL` before any `app` import.
- `docker compose up` does not restart a running api, so after `alembic downgrade base` restart the api (or run `alembic upgrade head`) before using it.
