# Handoff — Stage 4: Durable scheduler + worker

**Goal:** "publish at 9:00" survives crashes.
**Stage start commit:** `15f0be7`

## Context to read (only these)
- Vault: [[System Map]], [[Publishing Service]], [[Data Model]], [[Api Layer]], [[Fake Platform]], [[ADR-002 Publish flow]], [[API]]
- Source: `app/worker/__main__.py`, `app/models.py` (`Job`), `app/repos/campaigns.py`, `app/services/publishing.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/config.py`, `migrations/versions/0002_publish.py`, `fake_platform/main.py` (`Control`), `scripts/probes/_stage3_lib.sh`, `Makefile`, `.env.example`, `tests/unit/test_publishing.py`, `tests/conftest.py`

## Design (decided — do not redesign)
- **Job = "publish this campaign".** `kind = 'publish_campaign'`, `payload = {"campaign_id": <int>}`. The handler calls `publishing.publish_campaign(session, campaign_id)` **unchanged** ([[ADR-002 Publish flow]]). Duplicate safety on a re-run comes from what Stage 3 already guarantees: accepted entries are skipped, an in-flight entry reuses its committed idempotency key.
- **Claim** (one statement, then commit before running):
  `UPDATE jobs SET status='running', attempts=attempts+1, locked_until=now()+lease WHERE id = (SELECT id FROM jobs WHERE (status='pending' AND run_at<=now()) OR (status='running' AND locked_until<now()) ORDER BY run_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING …`
  The second branch is lease expiry: a killed worker's job is reclaimed once `locked_until` passes.
- **Lease heartbeat:** while a job runs, a daemon thread with its **own** session renews `locked_until = now()+lease WHERE id=:id AND status='running'` every `lease/3` seconds, and stops when the job ends. `publish_campaign` stays unchanged even when Retry-After waits make a job longer than the lease.
- **Outcomes:** handler returns → `status='done', locked_until=NULL, last_error=NULL`. Handler raises → if `attempts < JOB_MAX_ATTEMPTS`, set `status='pending'`, `run_at = now() + backoff` (reuse the full-jitter backoff idea, capped), `last_error = exception type + message[:200]`; otherwise `status='failed'`. The worker loop never dies on a job exception. Log one line per claim/outcome, with no tokens.
- **One active job per campaign:** a partial unique index on `((payload->>'campaign_id'))` `WHERE kind='publish_campaign' AND status IN ('pending','running')`. Enqueue while one is active → 409. Race-safe because the DB enforces it.
- **`POST /campaigns/{id}/publish` no longer blocks.** It enqueues a job due now and returns **202** + `JobOut`. Same 404/409 rules as schedule.
- **`POST /campaigns/{id}/schedule`** body `{"run_at": <ISO-8601 datetime with timezone>}` → **202** + `JobOut`. A naive datetime or a bad body → 422; a missing campaign → 404; an active job → 409. A past `run_at` is allowed (runs at once).
- **`GET /jobs/{id}`** → `JobOut` or 404. `JobOut = {id, kind, campaign_id, run_at, status, attempts, last_error, locked_until}`.
- **Test clock (dev only):** `POST /_dev/advance-time {"seconds": int 1..86400}` moves time forward for jobs. It shifts `run_at` of `pending` jobs **and** `locked_until` of `running` jobs back by N seconds, and returns `{"shifted": <count>}`. It is registered only when `DEV_ENDPOINTS=true` (setting, default `false`; `.env.example` sets `true`; also add it to your local `.env`). Out-of-range or non-int seconds → 422. When the setting is off the route is a 404.
- **Settings** (`app/config.py`, `.env.example`): `JOB_LEASE_SECONDS=30`, `JOB_MAX_ATTEMPTS=5`, `WORKER_POLL_SECONDS=1`, `DEV_ENDPOINTS`.
- **Fake platform:** add `latency_ms: int = Field(0, ge=0, le=10000)` to `Control` / `ControlUpdate`. `POST /v1/posts` sleeps that long **after** storing the post and before responding, so a killed caller leaves an accepted post behind, which is the worst case for duplicates. `/_control/reset` clears it.
- **Layering:** SQL in `app/repos/jobs.py`; `schedule_campaign` / `publish_now` / `advance_time` in `app/services/jobs.py`; worker loop + `run_once(session_factory) -> bool` in `app/worker/runner.py` (unit-testable); `app/worker/__main__.py` just loops `run_once` and sleeps `WORKER_POLL_SECONDS` when idle.

## Tasks — Iteration 1
| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 1 | Backend | Migration `0003_jobs`: `jobs.last_error text` + the partial unique index. Downgrade reverses both. Update `Job` model. | `migrations/versions/0003_jobs.py`, `app/models.py` | `docker compose run --rm api alembic downgrade 0002 && … upgrade head` → both succeed |
| 2 | Backend | `app/repos/jobs.py` (enqueue, claim, renew, complete, retry_or_fail, get, advance) + `app/services/jobs.py` | as named | unit tests below pass |
| 3 | Backend | Worker runner with heartbeat thread; `__main__` loop | `app/worker/runner.py`, `app/worker/__main__.py` | `docker compose logs worker` shows claim/done lines after a publish |
| 4 | Backend | Routes + schemas: publish → 202 enqueue, `/schedule`, `GET /jobs/{id}`, `/_dev/advance-time` (flagged). Settings + `.env.example`. | `app/api/routes.py`, `app/api/schemas.py`, `app/config.py`, `.env.example`, `.env` | `curl -X POST :8000/campaigns/<id>/schedule -d '{"run_at":"2026-01-01T00:00:00"}'` → 422 (naive) |
| 5 | Backend | Fake platform `latency_ms` control | `fake_platform/main.py`, `tests/unit/test_fake_platform.py` | latency test passes; `make probe` still green |
| 6 | Backend | Keep the Stage 3 probes green: `publish()` in `_stage3_lib.sh` now POSTs publish, polls `GET /jobs/{id}` until `done`/`failed` (timeout 180 s), then prints `GET /campaigns/{id}`. Update existing unit tests that expected a synchronous 200. | `scripts/probes/_stage3_lib.sh`, `tests/unit/test_publishing.py`, other probe scripts only if needed | `make probe1 probe2 probe6` → ALL PASS |
| 7 | Backend | **Probe 3** `scripts/probes/probe3_worker_crash.sh` + `make probe3`. Reset the fake platform, set `latency_ms` 1500, create 4 campaigns × `["instagram","x"]`, schedule all 4 with `run_at` = now+60 s, `advance-time 60`, wait until ≥1 fake-platform post exists but fewer than 8, `docker compose kill worker`, assert at least one job is still `running`, `docker compose up -d worker`, `advance-time` past the lease so the orphaned jobs are reclaimed at once, wait (timeout 120 s) for all 4 jobs `done`. Assert: all 8 entries have a `platform_post_id`; each entry's key has exactly 1 post in `GET /_posts`; `_posts` total = 8. Reset `latency_ms` to 0 at the end. | `scripts/probes/probe3_worker_crash.sh`, `Makefile` | `make probe3` → ALL PASS |
| 8 | Backend | Unit tests (`tests/unit/test_jobs.py`): two sessions claim concurrently → different jobs, never the same one (SKIP LOCKED); a future `run_at` is not claimed; an expired lease is reclaimed and a live one is not; a handler exception → pending with a later `run_at` + `last_error`, and at `JOB_MAX_ATTEMPTS` → failed; heartbeat extends `locked_until`; schedule 202/404/409/422 (naive); publish 202; `GET /jobs` 404; advance-time shifts pending + running and returns 404 when the flag is off; a run_once end-to-end against the fake transport publishes the campaign. | `tests/unit/test_jobs.py` | `make up && make test && make lint` → all green |
| 9 | Backend | Vault: new [[Worker]] module note (`vault/Modules/Worker.md`); update [[Publishing Service]] (the shortcut is gone; the worker is the caller), [[Data Model]] (0003), [[Api Layer]], [[API]] (new endpoints, publish now 202), [[Fake Platform]] (`latency_ms`), [[System Map]] if the wiring changed. | `vault/Modules/*`, `vault/Architecture/*` | notes mention every changed file |

## Out of scope
- Do not change `publish_campaign`'s logic or the Stage 3 conditional writes.
- Entries that used their 5 publish attempts stay `failed` (no "retry later" for entries in this stage).
- No webhook work (Stage 5), no UI.

## Blockers
_Agents write questions here instead of guessing._

## Backend report — Iteration 1
**Files changed**
- New: `migrations/versions/0003_jobs.py`, `app/repos/jobs.py`, `app/services/jobs.py`, `app/worker/runner.py`, `scripts/probes/probe3_worker_crash.sh`, `tests/unit/test_jobs.py`, `vault/Modules/Worker.md`
- Changed: `app/models.py` (`Job.last_error`, partial unique index, `campaign_id` property), `app/config.py` (4 settings), `app/api/schemas.py` (`ScheduleIn`, `AdvanceTimeIn`, `JobOut`), `app/api/routes.py` (publish → 202, `/schedule`, `/jobs/{id}`, `dev_router` with `/_dev/advance-time`), `app/main.py` (includes `dev_router` only if `DEV_ENDPOINTS`), `app/services/errors.py` (`Conflict`), `app/worker/__main__.py`, `fake_platform/main.py` (`latency_ms`), `scripts/probes/_stage3_lib.sh` (`publish` = enqueue + `job_wait` + GET campaign), `Makefile` (`probe3`), `.env.example` + local `.env` (`DEV_ENDPOINTS=true`; the other three use defaults), `tests/conftest.py` (`DEV_ENDPOINTS=true`), `tests/unit/test_publishing.py` (2 endpoint tests now 202 + `run_once`), `tests/unit/test_fake_platform.py` (latency test)
- Vault: [[Worker]] (new), [[Publishing Service]], [[Data Model]], [[Api Layer]], [[Fake Platform]], [[API]], [[System Map]] (worker → publishing service, api enqueues), [[00 Home]] map link

**Decisions (within the design)**
- `run_at` / `locked_until` columns are `timestamp without time zone`, so `ScheduleIn` takes an `AwareDatetime` and converts it to naive UTC in the schema; an offset that pushes it outside Python's datetime range (e.g. `9999-12-31T23:59:59-14:00`) → 422, not 500. `JobOut` times are therefore naive UTC strings (no `Z`).
- Job retry delay reuses `publishing.backoff_seconds(attempts)` (full jitter, base 500 ms, cap 30 s).
- `last_error` stores `"<Type>: <message>"[:200]`; the worker log line only prints the type.
- `complete` / `retry_or_fail` / `renew` only touch rows still `running`.
- The off-flag test reloads `app.main` with `dev_endpoints=False` and checks the real app gives 404 (then reloads it back).
- Worker sets the `httpx` logger to WARNING (request lines are noise; they never contained tokens anyway).

**How to run:** `make up`, then `curl -X POST :8000/campaigns/<id>/publish` → 202 `{id,...}`; poll `GET :8000/jobs/<job id>`; `docker compose logs worker` shows `job N claimed …` / `job N done`. Schedule: `POST /campaigns/<id>/schedule {"run_at":"2030-01-01T09:00:00+02:00"}`; fast-forward with `POST /_dev/advance-time {"seconds":N}`.

**Commands run (once, in order, after the last code change)**
```
$ make up        → exit 0 … Container socialmediamanager-api-1 Healthy
$ make test      → 271 passed, 2 warnings in 15.34s
$ make lint      → All checks passed! / 68 files already formatted
$ make probe     → … PASS 3 posts stored / PASS reset clears posts (0 FAIL)
$ make probe1 probe2 probe6 probe3   → exit 0; 49 PASS, 0 FAIL; ALL PASS ×4
  probe2 gaps: [2.02, 2.05] s (seconds), [2.28, 2.98] s (http-date)
  probe3: {"shifted":4} / killed the worker with 1 post(s) on the fake platform
          PASS killed mid-run (1..7 posts) / PASS at least one job still running (orphaned)
          PASS job 17..20 done / PASS 8 × "exactly 1 post" / PASS 8 posts in total
          worker log: … job 20 done / job 17 claimed kind=publish_campaign attempt=2 / job 17 done
          ALL PASS
```
Also: `docker compose run --rm api sh -c "alembic downgrade 0002 && alembic upgrade head && alembic current"` → `0003 (head)`; live `curl … /schedule -d '{"run_at":"2026-01-01T00:00:00"}'` → 422.

**Uncertain / for the Tester**
- Crash loops are not capped: `attempts` only gates handler *exceptions*; a job reclaimed after repeated worker kills keeps being reclaimed (noted as a shortcut in [[Worker]]). Not required by the design.
- The worker does not run migrations; after `make up` with a new migration it logs `worker loop error: ProgrammingError` until the api has migrated, then recovers (seen once in this run). `docker-compose.yml` was out of scope, so no `depends_on: api`.
- `/_dev/advance-time` also expires *live* leases; harmless with one worker (heartbeat renews it), but with 2+ workers it could hand a running job to a second worker. Dev only.
- Worth probing: concurrent `POST /publish` on one campaign (expect exactly one 202, rest 409), schedule bodies with odd offsets/leap seconds, `GET /jobs/<2^63>` → 422.
## Tester — Iteration 1 — PASS
| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Boot | PASS | `make up` → api, worker, db, web, fake-platform `Healthy`; `curl :8000/health` 200, `curl :9000/health` 200 |
| Unit tests + coverage | PASS | `make test` → `271 passed, 2 warnings in 14.55s`; `pytest -q --cov=app --cov=fake_platform` → TOTAL 97 %, `repos/jobs.py` 100 %, `services/jobs.py` 97 %, `worker/runner.py` 96 % |
| Lint / format | PASS | `make lint` → `All checks passed!` / `68 files already formatted` |
| T1 migration round trip | PASS | `docker compose run --rm api sh -c "alembic downgrade 0002 && alembic upgrade head && alembic current"` → `0003 (head)`; `\d jobs` shows `last_error text` + `uq_jobs_active_campaign UNIQUE ... WHERE kind='publish_campaign' AND status IN ('pending','running')` |
| T3 worker logs | PASS | publish job 40 → `job 40 claimed kind=publish_campaign attempt=1` / `job 40 done`; `docker compose logs worker \| grep -ciE "token\|secret\|bearer\|gAAAA"` → 0 |
| T4 naive run_at | PASS | `POST /campaigns/1482/schedule {"run_at":"2026-01-01T00:00:00"}` → 422 |
| T6/regression probes | PASS | `make probe` exit 0 (21 PASS); `make probe5` ALL PASS (9); `make probe1` ALL PASS (11); `make probe2` ALL PASS (10, gaps [2.05, 2.02] s / [2.43, 3.02] s); `make probe6` ALL PASS (8) |
| T7 / PLAN agent check: probe 3 | PASS | `make probe3` → `killed the worker with 1 post(s)` / `PASS at least one job still running (orphaned)` / `PASS job 21..24 done` / 8 × `exactly 1 post` / `PASS 8 posts in total` / log `job 21 claimed ... attempt=2` → `job 21 done` / `ALL PASS` |
| Claim SQL | PASS | `repos/jobs.py::claim`: one `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)` with branch `status='running' AND locked_until < now()`; commit before running; DB tz `Etc/UTC` so naive-UTC columns vs `now()` agree |
| Heartbeat | PASS | `runner._heartbeat` opens its own `session_factory()` per beat; `stop.set()` + `beat.join()` in `finally`; `test_heartbeat_keeps_the_lease_alive` green |
| Handler exception never kills loop | PASS | handler call wrapped in `except Exception` (unknown kind → KeyError also caught); outcome-write errors bubble to `__main__` `except Exception` → `worker loop error`, loop continues (seen live: `worker loop error: ProgrammingError` during my migration downgrade, next job 40 `done`) |
| 409 enforced by DB index | PASS | 8 concurrent `POST /schedule` on campaign 1482 → `202` ×1, `409` ×7; service catches `IntegrityError` from the unique index, no read-then-write |
| `/_dev/advance-time` flag off | PASS | `docker compose run --rm -e DEV_ENDPOINTS=false api python -c ...TestClient...` → `flag off advance-time -> 404`, `openapi has _dev: False` |
| No 500 on bad input | PASS | /schedule: garbage string, empty body, malformed JSON, null, array body, `9999-12-31T23:59:59-14:00`, `0001-01-01T00:00:00+14:00`, campaign 0 / 2^63 / abc → 422; missing campaign → 404. /jobs: abc, -1, 2^63 → 422; 999999999 → 404. /_dev/advance-time: 0, 86401, 1.5, "5", true, 1e309, malformed → 422 |

**Observations (not issues)**
- Attempt cap on crash loops: `claim` increments `attempts` but does not check `JOB_MAX_ATTEMPTS`, so a job whose run kills the worker every time is reclaimed forever (attempts can pass 5). This does not break Stage 4: the goal is crash survival with zero duplicates, which probe 3 shows, and the cap in the design only covers handler exceptions. Not filed. Worth a cap before anything production-like.
- `{"run_at": 12345}` → 202: pydantic `AwareDatetime` reads ints as Unix-epoch UTC (job 31 ran with `run_at 1970-01-01 03:25:45`). It is an unambiguous UTC instant, not a 500, but the contract says ISO-8601. Senior Dev's call whether to add `strict`/string-only.
- No fencing token: if a lease expires while the first worker is still alive (e.g. `/_dev/advance-time` with 2+ workers), the old worker's `renew`/`complete` still match `status='running'`. Harmless with the single worker in compose; duplicate safety still rests on Stage 3 idempotency keys.
- Leftover test data: campaign 1482 has a pending job at 2030-01-01; harmless for probes.

Issues: none.
