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
