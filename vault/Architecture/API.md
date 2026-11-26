# API Contract

The frontend uses only what is listed here. Backend: update this in the same change as the endpoint.

| Method | Path | Purpose | Request | Response | Errors | Stage |
|---|---|---|---|---|---|---|
| GET | /health | liveness | — | `{status}` | — | 0 |
| POST | /posts | create a post | `{title (1–200), body (1–20000), source_url? (http/https), image_b64? (PNG/JPEG, ≤5 MB, ≤25 MP)}` | 201 `{id, title, created_at}` | 422 | 2 |
| POST | /campaigns | generate images + captions for a post | `{post_id, platforms: ["instagram"\|"x", ...] (non-empty, unique), brand_name? (≤60)}` | 201 `{id, post_id, brand_name, created_at, entries: [{id, platform, caption, image_url, image_width, image_height, status}]}` | 404 unknown post, 422 | 2 |
| GET | /campaigns/{id} | read a campaign | — | same as POST /campaigns | 404, 422 bad id | 2 |
| any | any (api, port 8000) | request body cap | body > 8 MB (declared `Content-Length` or streamed size) | 413 `{detail}` before parsing | 413 | 2 |
| GET | /media/{file} | generated PNGs (`image_url`) | — | `image/png` | 404 | 2 |

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
