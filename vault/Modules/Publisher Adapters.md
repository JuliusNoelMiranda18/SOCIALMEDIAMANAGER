# Publisher Adapters

**Purpose:** The `SocialPublisher` protocol and the two fake-platform adapters. Each `publish()` makes exactly one HTTP attempt (plus at most one token refresh on 401) and returns a typed outcome; retries live in [[Publishing Service]] (see [[ADR-002 Publish flow]]).
**Files:** `app/publishers/__init__.py`, `app/publishers/fake.py`
**Last changed:** Stage 3 iteration 2, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `SocialPublisher` | `Protocol: publish(req) -> PublishOutcome` | the only type services depend on |
| `PublishRequest` | dataclass `platform, caption, image_url, idempotency_key` | holds no token |
| `PublishOutcome` | dataclass `kind` = `accepted` / `rate_limited` / `retryable` / `fatal`, plus `platform_post_id`, `wait_seconds`, `reason` | typed result |
| `get_publisher` | `(platform) -> SocialPublisher` | factory; imports adapters lazily |
| `FakeInstagramPublisher` | `(client=None)` | no image → `fatal` without a request |
| `FakeXPublisher` | `(client=None)` | caption > 280 → `fatal` without a request |
| `_send` | `(client, req)` | shared HTTP call and status mapping; never raises on a malformed reply |
| `retry_after_seconds` | `(value) -> float \| None` | integer seconds or HTTP-date (past date → 0); missing/garbage → `None` |

## Status mapping
2xx with a non-empty string `id` → accepted(id) · 2xx that is not JSON or lacks a string `id` → retryable("malformed response"; the same key makes the replay safe) · token endpoint 2xx without `access_token` → retryable("bad token response") · 429 + valid `Retry-After` → rate_limited(wait) · 429 without a valid one → retryable · 5xx, timeout, connection error, token endpoint failure → retryable · 401 → refresh token, resend once (second 401 → fatal) · other 4xx → fatal.

## Connections
- Depends on: [[Token Crypto]] (`get_token`), [[Fake Platform]] (`FAKE_PLATFORM_URL`), `httpx`
- Used by: [[Publishing Service]] (via the protocol and factory only) · map: [[System Map]]

## Invariants
- One HTTP request per `publish()`, plus at most one refresh-and-resend on 401.
- Services never import an adapter class (`test_services_import_no_adapter_class`).
- No token or `Authorization` header is logged or held in a dataclass.

## Tests
- `tests/unit/test_publishers.py` — `httpx.MockTransport`: 201, 429 (seconds, HTTP-date, missing, garbage), 503, timeout, connection error, 400, 422, 401-then-ok, 401 twice, platform rules, factory; one request per call; malformed 2xx shapes and bad token bodies → retryable ([[ISSUE-007 2xx without id or bad token body returns 500]])
- `scripts/probes/probe2_rate_limit.sh` — live Retry-After in both formats

## Gotchas
- The default `httpx.Client` is module-level and shared (timeout `PUBLISH_TIMEOUT_SECONDS`); tests pass their own client.
- An HTTP-date only has second precision; the fake platform rounds its date up so a client honouring it never returns early.
