# Social Campaign Publisher

Schedules and publishes campaign posts to social platforms, with idempotent publishing, a durable worker and a signed status webhook.

## Run
```
cp .env.example .env
make up      # docker compose up -d --build --wait
make test    # pytest in container
make lint    # ruff in container
make probe   # curl probe of the live fake platform (needs make up)
make seed    # create one sample post, prints its id (needs make up)
make probe5  # post -> campaign -> checks images, captions, llm_calls (needs make up)
```

## Content generation
`POST /posts` then `POST /campaigns {post_id, platforms}` renders a 1080×1080 Instagram and 1600×900 X image (served under `/media`) and one caption per platform.
Captions come from `LLM_PROVIDER`: `none` (default, deterministic templates) or `gemini` (needs `GEMINI_API_KEY`, `GEMINI_MODEL`; `LLM_TIMEOUT_SECONDS` default 10). Any model failure or rule-breaking reply falls back to the template. Every call writes one row to `llm_calls`.
API: http://localhost:8000/health · Fake platform: http://localhost:9000/health · Web: http://localhost:5173

## Fake platform
The fake platform is built in-house because the starter was never shipped.
Switches via `POST :9000/_control` (`rate_limit`, `failure_rate`, `drop_response`, `forged_signature`, `webhook_url`); `POST :9000/_control/reset` clears everything. `make probe` exercises each one. See `vault/Modules/Fake Platform.md`.

## Architecture
_Diagram placeholder (see `vault/Architecture/System Map.md`)._

## Limitations
_TBD._
