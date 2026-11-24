# API Contract

The frontend uses only what is listed here. Backend: update this in the same change as the endpoint.

| Method | Path | Purpose | Request | Response | Errors | Stage |
|---|---|---|---|---|---|---|
| GET | /health | liveness | — | `{status}` | — | 0 |

## Fake platform (port 9000)
| Method | Path | Purpose | Stage |
|---|---|---|---|
| GET | /health | liveness | 0 |
| POST | /oauth/token | form `grant_type=client_credentials`, `client_id`, `client_secret` -> Bearer token (400 if invalid) | 1 |
| POST | /v1/posts | publish; needs Bearer + `Idempotency-Key`; 201 / 400 / 401 / 422 / 429 (`Retry-After`) / 503 | 1 |
| GET | /_posts | list stored posts | 1 |
| GET | /_control | current switches | 1 |
| POST | /_control | partial update: `rate_limit`, `failure_rate`, `drop_response`, `forged_signature`, `webhook_url` (422 on bad values) | 1 |
| POST | /_control/reset | clear posts, keys, tokens; switches to defaults | 1 |
