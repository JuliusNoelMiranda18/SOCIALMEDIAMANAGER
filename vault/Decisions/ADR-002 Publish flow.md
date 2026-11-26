# ADR-002 Publish flow, idempotency key and retry ownership

**Status:** accepted · 2026-11-26 · Stage 3

**Decision:**
- The unit of publishing is one `social_post_entries` row (one campaign × one platform). Its idempotency key is derived from it (`sha256("<campaign_id>:<post_id>:<platform>")`, hex), written to the row and committed **before** the first network call, and reused on every retry. This honours PLAN.md's "(post_id, platform)" while letting the same blog post run in more than one campaign.
- Adapters (`FakeInstagramPublisher`, `FakeXPublisher`) make exactly one HTTP attempt and return a typed outcome (accepted / rate limited with wait / retryable / fatal). The **service** owns the retry loop: Retry-After (seconds or HTTP-date), exponential backoff with full jitter, max attempts. App code depends only on the `SocialPublisher` protocol.
- Until Stage 4, publishing runs synchronously from `POST /campaigns/{id}/publish`. Stage 4 moves the same service call into the jobs worker unchanged.
- A 201 from the platform moves an entry to `publishing`, not `published`: only a verified webhook (Stage 5) may mark it published.

**Why:** keys stored before the call make timeout-after-accept safe to retry; keeping retries out of adapters means one tested policy for every platform; the synchronous endpoint lets Stage 3 be probed without building the worker early.

**Rejected:** retry inside each adapter (duplicated policy); key from `(post_id, platform)` only (a second campaign for the same post would be silently replayed and never publish).

Links: [[ADR-001 Stack]] · [[System Map]] · [[Stage 3]]
