# Social Campaign Publisher

Schedules and publishes campaign posts to social platforms, with idempotent publishing, a durable worker and a signed status webhook.

## Run
```
cp .env.example .env
make up      # docker compose up -d --build --wait
make test    # pytest in container
make lint    # ruff in container
make probe   # curl probe of the live fake platform (needs make up)
```
API: http://localhost:8000/health · Fake platform: http://localhost:9000/health · Web: http://localhost:5173

## Fake platform
The fake platform is built in-house because the starter was never shipped.
Switches via `POST :9000/_control` (`rate_limit`, `failure_rate`, `drop_response`, `forged_signature`, `webhook_url`); `POST :9000/_control/reset` clears everything. `make probe` exercises each one. See `vault/Modules/Fake Platform.md`.

## Architecture
_Diagram placeholder (see `vault/Architecture/System Map.md`)._

## Limitations
_TBD._
