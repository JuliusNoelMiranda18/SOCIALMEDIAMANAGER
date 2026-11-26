# Api Layer

**Purpose:** HTTP entrypoint (FastAPI), settings, the `/media` static mount, and the services that back the post/campaign endpoints.
**Files:** `app/main.py`, `app/config.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/services/posts.py`, `app/services/campaigns.py`, `app/services/errors.py` (`NotFound`, `InvalidInput`, `Conflict`)
**Last changed:** Stage 4, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `health` | `GET /health -> {"status":"ok"}` | liveness for compose healthcheck |
| `create_post` | `POST /posts` | Pydantic validation, then `services.posts.create_post` (image check → 422) |
| `create_campaign` | `POST /campaigns` | `services.campaigns.create_campaign`; unknown post → 404 |
| `get_campaign` | `GET /campaigns/{id}` | 404 if missing |
| `publish_campaign` | `POST /campaigns/{id}/publish` | enqueue a job due now via `services.jobs` ([[Worker]]) → 202 `JobOut`; 404 unknown, 409 active job, 422 bad id |
| `schedule_campaign` | `POST /campaigns/{id}/schedule` `{run_at}` | `ScheduleIn.run_at` must be timezone-aware (`AwareDatetime`), converted to naive UTC (overflow → 422) → 202 `JobOut`; 404 / 409 / 422 |
| `get_job` | `GET /jobs/{id}` | `JobOut` or 404 |
| `advance_time` | `POST /_dev/advance-time` `{seconds: strict int 1..86400}` | on `dev_router`, included by `app/main.py` only when `DEV_ENDPOINTS=true`; `{shifted}` |
| startup key check | `app/main.py` import | invalid `TOKEN_ENCRYPTION_KEY` → api exits with a clear message ([[Token Crypto]]) |
| `_invalid` | `RequestValidationError` handler | 422 without echoing input (NaN / lone surrogates would otherwise 500) |
| `services.campaigns.create_campaign` | `(session, post_id, platforms, brand_name)` | images + captions + `llm_calls` in one transaction; on any error rolls back and deletes written files |
| `Settings` | pydantic-settings | DB URL, fake platform URL, secrets, `MEDIA_DIR`, LLM settings; Stage 3: `FAKE_CLIENT_ID/SECRET`, `PUBLIC_BASE_URL`, `PUBLISH_TIMEOUT_SECONDS`, `PUBLISH_MAX_ATTEMPTS`, `BACKOFF_BASE_MS`, `BACKOFF_CAP_MS`, `MAX_RETRY_AFTER_SECONDS`; Stage 4: `JOB_LEASE_SECONDS`, `JOB_MAX_ATTEMPTS`, `WORKER_POLL_SECONDS`, `DEV_ENDPOINTS` (default false) |

## Connections
- Depends on: [[Worker]] (job services), [[Data Model]], [[Image Pipeline]], [[Caption Composer]], [[Publishing Service]], [[Token Crypto]]
- Used by: [[System Map]], [[API]]

## Invariants
- Layers: api → services → repos. Handlers hold no SQL; services hold no HTTP.
- Validation failures are 4xx, never 500. Unexpected generation failures return 500 and save nothing.
- Secrets from env only.
- Request bodies over 8 MB (`MAX_BODY`) get 413 from the `BodyLimit` ASGI middleware in `app/main.py`, before any parsing; it counts streamed bytes too, so chunked bodies without `Content-Length` are capped.

## Tests
- `tests/test_health.py` — `/health`
- `tests/unit/test_jobs.py` — publish/schedule/jobs/advance-time endpoints (see [[Worker]])
- `tests/unit/test_api.py` — happy path, 4xx matrix for posts/campaigns/GET, failed generation saves nothing, >8 MB body → 413 (declared, garbage and chunked) and a normal campaign still 201

## Gotchas
- `MEDIA_DIR` is bind-mounted from `./media` in compose; tests use a temp dir.
