# Data Model

**Purpose:** SQLAlchemy 2 models for all seven tables, the engine/session, and the single Alembic migration that creates them.
**Files:** `app/models.py`, `app/db.py`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `migrations/versions/0002_publish.py`, `migrations/versions/0003_jobs.py`, `app/repos/posts.py`, `app/repos/campaigns.py`, `app/repos/tokens.py`
**Last changed:** Stage 4, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `Post`, `Campaign`, `SocialPostEntry`, `PlatformToken`, `Job`, `WebhookEvent`, `LlmCall` | declarative models | BIGINT identity ids, integer money/token/latency fields |
| `SocialPostEntry.image_url` | property | `/media/<image_path>` |
| `get_session` | FastAPI dependency | one `Session` per request |
| `repos.posts.add/get`, `repos.campaigns.add/add_entry/get` | `(session, ...)` | flush-only inserts (caller commits); `get` eager-loads entries |
| `0001_initial` | Alembic revision | creates all 7 tables; downgrade drops them |
| `0002_publish` | Alembic revision | `social_post_entries` + `idempotency_key` (text, UNIQUE, nullable), `attempts` (int, default 0), `last_error` (text); downgrade drops them |
| `0003_jobs` | Alembic revision | `jobs.last_error` (text) + partial unique index `uq_jobs_active_campaign` on `((payload->>'campaign_id')) WHERE kind='publish_campaign' AND status IN ('pending','running')`; downgrade drops both |
| `Job.campaign_id` | property | `payload['campaign_id']` (for `JobOut`) |
| `repos.jobs.*` | see [[Worker]] | claim / renew / complete / retry_or_fail / enqueue / get / advance |
| `repos.tokens.get/upsert` | `(session, platform, ...)` | `platform_tokens` read and `ON CONFLICT (platform)` upsert, see [[Token Crypto]] |

## Connections
- Depends on: Postgres (`DATABASE_URL`)
- Used by: [[Api Layer]], [[Worker]], [[Caption Composer]] (writes `llm_calls`), [[Publishing Service]] (entry publish state), [[Token Crypto]] (`platform_tokens`), [[System Map]]

## Invariants
- `UNIQUE(campaign_id, platform)` and `UNIQUE(idempotency_key)` on `social_post_entries` (the unique index also serves key lookups); `platform_tokens.platform` and `webhook_events.event_id` unique.
- Indexes: `campaigns.post_id`, `llm_calls.entry_id`, `jobs(status, run_at)` for the Stage 4 worker.
- `jobs` is used by the [[Worker]] (Stage 4); `webhook_events` is a table only until Stage 5.
- One active publish job per campaign (`uq_jobs_active_campaign`).
- The api container runs `alembic upgrade head` before uvicorn.

## Tests
- `tests/conftest.py` — creates `app_test`, migrates to head, truncates all tables after each test
- `tests/unit/test_api.py` — rows exist after the happy path; nothing saved on failure

## Gotchas
- `migrations/env.py` reads `settings.database_url`, so tests point alembic at `app_test` by setting `DATABASE_URL` before any `app` import.
- `docker compose up` does not restart a running api, so after `alembic downgrade base` restart the api (or run `alembic upgrade head`) before using it.
- `alembic downgrade base` wipes the dev DB but not `./media`, so campaign ids restart and collide with stale PNGs (this broke `stage2_tester.sh`'s fault symlink once). Delete stale `media/<id>_*.png` above `max(campaigns.id)` after a reset.
