# Api Layer

**Purpose:** HTTP entrypoint (FastAPI), settings, the `/media` static mount, and the services that back the post/campaign endpoints.
**Files:** `app/main.py`, `app/config.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/services/posts.py`, `app/services/campaigns.py`, `app/services/errors.py`, `app/worker/__main__.py`
**Last changed:** Stage 3, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `health` | `GET /health -> {"status":"ok"}` | liveness for compose healthcheck |
| `create_post` | `POST /posts` | Pydantic validation, then `services.posts.create_post` (image check → 422) |
| `create_campaign` | `POST /campaigns` | `services.campaigns.create_campaign`; unknown post → 404 |
| `get_campaign` | `GET /campaigns/{id}` | 404 if missing |
| `publish_campaign` | `POST /campaigns/{id}/publish` | [[Publishing Service]]; 404 unknown, 422 bad id |
| startup key check | `app/main.py` import | invalid `TOKEN_ENCRYPTION_KEY` → api exits with a clear message ([[Token Crypto]]) |
| `_invalid` | `RequestValidationError` handler | 422 without echoing input (NaN / lone surrogates would otherwise 500) |
| `services.campaigns.create_campaign` | `(session, post_id, platforms, brand_name)` | images + captions + `llm_calls` in one transaction; on any error rolls back and deletes written files |
| `Settings` | pydantic-settings | DB URL, fake platform URL, secrets, `MEDIA_DIR`, LLM settings; Stage 3: `FAKE_CLIENT_ID/SECRET`, `PUBLIC_BASE_URL`, `PUBLISH_TIMEOUT_SECONDS`, `PUBLISH_MAX_ATTEMPTS`, `BACKOFF_BASE_MS`, `BACKOFF_CAP_MS`, `MAX_RETRY_AFTER_SECONDS` |
| worker loop | `python -m app.worker` | idle; job claiming is Stage 4 |

## Connections
- Depends on: [[Data Model]], [[Image Pipeline]], [[Caption Composer]], [[Publishing Service]], [[Token Crypto]]
- Used by: [[System Map]], [[API]]

## Invariants
- Layers: api → services → repos. Handlers hold no SQL; services hold no HTTP.
- Validation failures are 4xx, never 500. Unexpected generation failures return 500 and save nothing.
- Secrets from env only.
- Request bodies over 8 MB (`MAX_BODY`) get 413 from the `BodyLimit` ASGI middleware in `app/main.py`, before any parsing; it counts streamed bytes too, so chunked bodies without `Content-Length` are capped.

## Tests
- `tests/test_health.py` — `/health`
- `tests/unit/test_api.py` — happy path, 4xx matrix for posts/campaigns/GET, failed generation saves nothing, >8 MB body → 413 (declared, garbage and chunked) and a normal campaign still 201

## Gotchas
- `MEDIA_DIR` is bind-mounted from `./media` in compose; tests use a temp dir.
