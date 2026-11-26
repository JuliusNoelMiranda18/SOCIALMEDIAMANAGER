# Stage 4 — Durable scheduler + worker

**Status:** AWAITING_APPROVAL · **Loops used:** 1/3 · **Date:** 2026-11-26

## Built
- **Jobs** ([[Data Model]], migration `0003_jobs`): `jobs.last_error` plus a partial unique index allowing one active (`pending`/`running`) publish job per campaign. A second enqueue gets 409, and the DB enforces it.
- **Worker** ([[Worker]], `app/worker/runner.py`): claims one due job in a single `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)`. It also reclaims jobs whose lease (`locked_until`) has expired. A heartbeat thread with its own session renews the lease every `lease/3`. If the handler raises, the job goes back to `pending` with backoff, and after `JOB_MAX_ATTEMPTS` it is `failed`. The loop never dies.
- **Publishing moved into the worker** ([[ADR-002 Publish flow]]): the job handler calls `publish_campaign`, which is unchanged. A re-run after a crash is safe because accepted entries are skipped and in-flight entries reuse their committed idempotency key.
- **API** ([[Api Layer]], [[API]]): `POST /campaigns/{id}/publish` now returns **202** + job (it no longer blocks). New: `POST /campaigns/{id}/schedule {"run_at": <tz-aware ISO-8601>}` and `GET /jobs/{id}`.
- **Test clock:** `POST /_dev/advance-time {"seconds": 1..86400}` moves pending `run_at` and running `locked_until` earlier. It is only registered when `DEV_ENDPOINTS=true`.
- **Fake platform** ([[Fake Platform]]): a `latency_ms` control. The post is stored before the delay, so a killed caller leaves an accepted post behind.
- **Probe 3** (`make probe3`): 4 campaigns × 2 platforms are scheduled, the worker is killed mid-batch and then restarted. Every entry ends with exactly 1 post.
- Stage 3 probes were updated: `publish()` in `_stage3_lib.sh` enqueues, then polls the job.

## Tester evidence
| Check | Result | Evidence |
|---|---|---|
| Unit tests | PASS | `make test` → `271 passed`; coverage 97%, new job code 96–100% |
| Lint | PASS | `make lint` → `All checks passed!`, `68 files already formatted` |
| Probe 3 (exit criterion) | PASS | `make probe3` → worker killed with 1 post, a job still `running`; job 21 reclaimed `attempt=2` → `done`; 8 × `exactly 1 post`; `8 posts in total`; `ALL PASS` |
| Regression | PASS | `make probe` (21), `probe5` (9), `probe1` (11), `probe2` (10), `probe6` (8) → all PASS |
| Migration round trip | PASS | `alembic downgrade 0002 && upgrade head` → `0003 (head)` |
| One active job per campaign | PASS | 8 concurrent `/schedule` → 1×202, 7×409 |
| Dev endpoint gated | PASS | `DEV_ENDPOINTS=false` → `/_dev/advance-time` 404, absent from OpenAPI |
| No 500 on bad input | PASS | ~25 bad cases on `/schedule`, `/jobs/{id}`, `/_dev/advance-time` → 422/404 |
| No secrets in worker logs | PASS | `grep -ciE "token\|secret\|bearer"` on worker logs → 0 |

## Your manual test (optional; steps from PLAN.md)
1. `make up`, then create a post + campaign (`make seed`, then `POST /campaigns`).
2. Schedule it 1 minute out: `curl -X POST localhost:8000/campaigns/<id>/schedule -H 'Content-Type: application/json' -d "{\"run_at\":\"$(date -u -v+1M +%Y-%m-%dT%H:%M:%SZ)\"}"` → 202 and a job id.
3. `docker compose kill worker`, wait past the minute, then `docker compose up -d worker`.
4. `curl localhost:8000/jobs/<job id>` → `done`; `curl localhost:9000/_posts` → one post per platform, with no duplicates.

## Known limitations
- A job that crashes the worker every time is reclaimed forever: `claim` increments `attempts` but does not cap expired-lease reclaims. The cap only covers handler exceptions.
- There is no fencing token. If a lease expires while the first worker is still alive (only possible with 2+ workers, or by using `advance-time`), that worker can still renew or complete the job. Duplicate sends are still prevented by the Stage 3 idempotency keys. Compose runs one worker.
- `{"run_at": 12345}` is accepted as a Unix-epoch UTC time (it is not a 500, but the contract says ISO-8601).
- The worker does not run migrations. Right after a migration it logs `ProgrammingError` until the api has migrated, then recovers.
- Entries that used all 5 publish attempts stay `failed`; there is no "retry later" for entries.

## Issues closed / still open
None filed. Open: none.

## Dead ends logged
None.

## Links
[[00 Home]] · [[_Stages Index]] · [[System Map]] · [[Worker]] · [[ADR-002 Publish flow]] · previous: [[Stage 3]]

## Next stage preview
Stage 5: the signed webhook plus status tracking. The fake platform's HMAC callback is verified in constant time and deduplicated by `event_id`, and only a verified webhook moves an entry from `publishing` to `published`.

## Approval
Approved by user on 2026-11-26.
