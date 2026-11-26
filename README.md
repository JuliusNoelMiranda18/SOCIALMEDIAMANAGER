# Social Campaign Publisher

Schedules and publishes campaign posts to social platforms, with idempotent publishing, a durable worker and a signed status webhook.

## Run
```
make env     # creates .env from .env.example (if missing) and fills a fresh TOKEN_ENCRYPTION_KEY
make up      # docker compose up -d --build --wait
make test    # pytest in container
make lint    # ruff in container
make probe   # curl probe of the live fake platform (needs make up)
make seed    # create one sample post, prints its id (needs make up)
make probe5  # post -> campaign -> checks images, captions, llm_calls (needs make up)
make probe1 probe2 probe6  # idempotent publish, Retry-After, no plaintext tokens (needs make up)
```

## Content generation
`POST /posts` then `POST /campaigns {post_id, platforms}` renders a 1080×1080 Instagram and 1600×900 X image (served under `/media`) and one caption per platform.
Captions come from `LLM_PROVIDER`: `none` (default, deterministic templates) or `gemini` (needs `GEMINI_API_KEY`, `GEMINI_MODEL`; `LLM_TIMEOUT_SECONDS` default 10). Any model failure or rule-breaking reply falls back to the template. Every call writes one row to `llm_calls`.
API: http://localhost:8000/health · Fake platform: http://localhost:9000/health · Web: http://localhost:5173

## Publishing
`POST /campaigns/{id}/publish` sends every entry through the `SocialPublisher` adapters (synchronous until Stage 4).
Each entry gets an idempotency key that is committed before the first call and reused on every retry, so publishing twice or retrying after a timeout never makes a second post.
429 `Retry-After` (seconds or HTTP-date) is honoured; other transient errors use exponential backoff with full jitter (`PUBLISH_MAX_ATTEMPTS` 5, `BACKOFF_BASE_MS` 500, `BACKOFF_CAP_MS` 30000, `MAX_RETRY_AFTER_SECONDS` 60, `PUBLISH_TIMEOUT_SECONDS` 5).
Platform tokens are stored AES-GCM encrypted (`TOKEN_ENCRYPTION_KEY`); the api refuses to start without a valid key.

## Fake platform
The fake platform is built in-house because the starter was never shipped.
Switches via `POST :9000/_control` (`rate_limit`, `failure_rate`, `drop_response`, `forged_signature`, `webhook_url`); `POST :9000/_control/reset` clears everything. `make probe` exercises each one. See `vault/Modules/Fake Platform.md`.

## Architecture
_Diagram placeholder (see `vault/Architecture/System Map.md`)._

## Limitations
_TBD._
