# Design — Multi-Platform Social Campaign Publisher

## Problem
A marketer writes one blog post. We turn it into per-platform captions and images
(Instagram, X), publish them on a schedule, and show real delivery status. The hard
parts are the ones that go wrong in production: duplicate posts on retry, rate limits,
crashed workers, forged callbacks and leaked tokens.

The platform API is simulated by a fake server we build ourselves (`fake_platform/`),
because the starter server was never shipped. No real social account is ever used.

## Data model (tables arrive in Stage 2)
| Table | Purpose |
|---|---|
| `posts` | source blog post: title, body, url |
| `campaigns` | one post + chosen platforms + schedule |
| `social_post_entries` | one row per (campaign, platform): caption, image path, idempotency key, status `queued → publishing → published \| failed`, platform post id |
| `platform_tokens` | per-platform OAuth token, AES-GCM encrypted (nonce + ciphertext) |
| `jobs` | durable queue: `run_at`, `status`, `attempts`, `locked_until`, payload |
| `webhook_events` | event id (unique, for dedupe), raw body, signature result |
| `llm_calls` | caption model calls: tokens (integers), cost in integer micro-USD, latency |

Money and token counts are integers everywhere.

## API surface
- Main API (port 8000): `GET /health` now; later `POST /posts`, `POST /campaigns`,
  `POST /campaigns/{id}/schedule`, `GET /campaigns/{id}`, `POST /webhook/social-delivery`,
  dev-only demo controls. Contract lives in `vault/Architecture/API.md`.
- Fake platform (port 9000): `GET /health` now; later `POST /oauth/token`,
  `POST /v1/posts` (honours `Idempotency-Key`), `POST /_control`, `GET /_posts`.

## Layers
```
HTTP (app/api) → services (app/services) → repos (app/repos) → Postgres
                       ├→ content (captions, images)
                       └→ SocialPublisher interface → FakeInstagram / FakeX adapters → fake_platform
worker (app/worker) claims jobs with FOR UPDATE SKIP LOCKED and calls services.
```
App code depends on the `SocialPublisher` interface only, never on an adapter.

## Non-goal
No real Instagram/X integration, no OAuth consent flow with real providers, no
multi-user accounts or auth for the dashboard.
