# Build Log

Honest log: what was tried, what failed, what changed.

Format per entry:
- **Date / stage**
- **What I did**
- **What went wrong or surprised me**
- **Decision**

## 2026-11-24 — Stage 0
- **What I did:** AI agents (senior-dev planned, backend-dev scaffolded, tester verified) built the repo skeleton, compose stack, Alembic wiring, smoke tests and pack files.
- **What went wrong or surprised me:** Docker Desktop was off at the start, so it was launched first. Host Python is 3.9 with no ruff, so all Python tooling runs in containers. The tester failed iteration 1 because `pytest-cov` was missing from dev deps; it was added in iteration 2.
- **Decision:** dependencies left unpinned and the worker has no SIGTERM handling for now (both logged as limitations; SIGTERM belongs to Stage 4).

## 2026-11-24 — Stage 1
- **What I did:** AI agents built the fake platform (`/oauth/token`, idempotent `/v1/posts`, `/_control` switches, `/_posts`, HMAC-signed callback) and a curl probe script.
- **What went wrong or surprised me:**
  - My first Stage 1 handoff write failed (file changed since I read it) and I dispatched backend-dev anyway. It correctly refused to guess from the stale Stage 0 handoff and built nothing. I should have checked the write landed before dispatching.
  - Iteration 1 FAIL: `ruff format --check` was not part of `make lint`, and `NaN`/`Infinity` for `failure_rate` returned 500. The obvious `allow_inf_nan=False` fix alone still gave a 500, because FastAPI's default 422 body echoes the NaN input and cannot be JSON-encoded. The fix also needed a custom validation-error handler that drops `input`/`ctx` from 422 bodies (all endpoints).
  - The tester also spotted that nested partial updates reset sibling fields; fixed to merge.
- **Decision:** a 429 or 503 stores no idempotency record (a retry with the same key is a fresh attempt). The same key with a different body replays the first response, as designed. Tokens never expire (`expires_in` is cosmetic).

## 2026-11-24 → 2026-11-26 — Stage 2
- **What I did:** AI agents built the data model + migration, posts/campaigns API, Pillow image pipeline, fragment-based caption composer and an LLM wrapper (template default, Gemini optional).
- **What went wrong or surprised me:**
  - The user paused the stage mid-build; the resumed backend run re-checked the partial files (no changes needed) before finishing. Pausing roughly doubled the backend token cost.
  - Iteration 1 FAIL: user input could make the X template exceed 280 chars (a negative length budget made the clip keep most of the title) and a `#fragment` URL added a third hashtag. Also the brand strip touched the safe margin by 1px. Both fixed with a final rule guard and regression + fuzz tests.
  - The tester showed a 30 MB request was accepted; an 8 MB body cap (413) was added.
- **Decision:** Gemini stays optional and mock-tested only (no key in the repo). Captions default to the deterministic template.

## 2026-11-26 — Stage 3
- **What I did:** AI agents built the SocialPublisher protocol and two fake adapters, the publish service with Retry-After/backoff/attempt cap, AES-GCM token storage and probes 1, 2, 6. Design fixed up front in ADR-002 (key per campaign entry, stored before the call; retries owned by the service).
- **What went wrong or surprised me:** it took all 3 loops.
  - Iter 1: a corrupt nonce, a 2xx without `id` and a malformed token reply each caused a 500 and could leave an entry stuck in `publishing`; concurrent publishes undercounted attempts.
  - Iter 2: the tester's stress test found that concurrent publishes could mark a post the platform had accepted as `failed` (22/25 runs). Cause: each request wrote status from its own stale ORM copy, last commit wins.
  - Iter 3: all status writes became conditional SQL updates (acceptance always wins; failure only without a post id; a late write can't undo `failed`). The first version only fixed two writes; the stress test showed two more late writes needed the same pattern.
  - A backend agent deleted 61 stale generated images in `./media` that collided with new campaign ids after a DB reset (test artifacts only).
- **Decision:** no locks or leases in Stage 3; the Stage 4 worker's claim handles concurrency properly. Publishing stays synchronous until then.

## 2026-11-26 — Stage 4
- **What I did:** AI agents built the durable jobs worker (`SKIP LOCKED` claim, lease with heartbeat, expired-lease reclaim, retry with backoff), moved publishing into it unchanged, added `/schedule`, `GET /jobs/{id}`, a flag-gated `/_dev/advance-time` test clock, a fake-platform `latency_ms` control and probe 3.
- **What went wrong or surprised me:** passed on the first loop. The Senior Dev fixed the design in the handoff up front (claim SQL, heartbeat, DB-enforced one-job-per-campaign), so the backend had nothing to invent. The tester noticed that crash-loop reclaims are uncapped and that an integer `run_at` is read as a Unix time; both were logged as known limitations rather than fixed.
- **Decision:** `POST /publish` now returns 202 and enqueues a job, so the Stage 3 probes poll the job. Duplicate safety on re-runs still rests on the Stage 3 idempotency keys; no fencing token.
