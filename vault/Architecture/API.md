# API Contract

The frontend uses only what is listed here. Backend: update this in the same change as the endpoint.

| Method | Path | Purpose | Request | Response | Errors | Stage |
|---|---|---|---|---|---|---|
| GET | /health | liveness | — | `{status}` | — | 0 |
| POST | /posts | create a post | `{title (1–200), body (1–20000), source_url? (http/https), image_b64? (PNG/JPEG, ≤5 MB, ≤25 MP)}` | 201 `{id, title, created_at}` | 422 | 2 |
| POST | /campaigns | generate images + captions for a post | `{post_id, platforms: ["instagram"\|"x", ...] (non-empty, unique), brand_name? (≤60)}` | 201 `{id, post_id, brand_name, created_at, entries: [{id, platform, caption, image_url, image_width, image_height, status, attempts, last_error, platform_post_id}]}`; `status`: `draft` → `queued` (job enqueued) → `publishing` (started / accepted, awaiting webhook) → `published` (verified callback; final) \| `failed` (retryable by a new publish) | 404 unknown post, 422 | 2 |
| GET | /campaigns/{id} | read a campaign | — | same as POST /campaigns | 404, 422 bad id | 2 |
| POST | /campaigns/{id}/publish | enqueue a publish job due now; the [[Worker]] publishes every entry not yet accepted ([[Publishing Service]]) | — | 202 `JobOut` | 404 unknown campaign, 409 campaign already has a pending/running job, 422 bad id | 3, 4 |
| POST | /campaigns/{id}/schedule | publish later | `{run_at}` ISO-8601 **with timezone** (past = run at once) | 202 `JobOut` | 404, 409 active job, 422 naive/bad datetime or body | 4 |
| GET | /jobs/{id} | poll a job | — | 200 `JobOut` = `{id, kind, campaign_id, run_at, status (pending\|running\|done\|failed), attempts, last_error, locked_until}`; times are naive UTC | 404, 422 bad id | 4 |
| POST | /_dev/advance-time | dev test clock (only when `DEV_ENDPOINTS=true`, else 404) | `{seconds: int 1..86400}` | 200 `{shifted}`: pending `run_at` and running `locked_until` moved N s earlier | 422, 404 when off | 4 |
| POST | /webhook/social-delivery | platform delivery callback ([[Webhook]]) | raw JSON `{event_id (1..200), post_id, status: delivered\|failed, timestamp (int, = header)}`; headers `X-Timestamp` (int, within ±`WEBHOOK_TOLERANCE_SECONDS`), `X-Signature` = hex HMAC-SHA256(`WEBHOOK_SECRET`, `"<ts>.<raw body>"`) | 200 `{result: applied\|unmatched\|duplicate}` | 400 `{detail}` (missing headers, bad/stale timestamp, bad signature, invalid body, timestamp mismatch); nothing stored | 5 |
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
| GET | /_stats | `{post_requests: [{at, idempotency_key, status}]}`, every `POST /v1/posts` (401s too) | 3 |
| GET | /_tokens | issued access tokens (dev-only, for probe 6) | 3 |
| POST | /_control | partial update: `rate_limit` (`enabled`, `retry_after_seconds`, `count` auto-off after N fresh 429s, `format` `seconds`\|`http-date`), `failure_rate`, `drop_response`, `forged_signature`, `webhook_url`, `latency_ms` (0..10000, sleep after storing the post; Stage 4) (422 on bad values) | 1, 4 |
| POST | /_control/reset | clear posts, keys, tokens, stats; switches to defaults | 1, 3 |
