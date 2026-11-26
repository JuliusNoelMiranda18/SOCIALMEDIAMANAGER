# Worker

**Purpose:** Durable scheduler: jobs in Postgres, claimed with a lease so "publish at 9:00" survives a crash. One job = "publish this campaign"; the handler is [[Publishing Service]]'s `publish_campaign`, unchanged.
**Files:** `app/worker/runner.py`, `app/worker/__main__.py`, `app/repos/jobs.py`, `app/services/jobs.py`, `migrations/versions/0003_jobs.py`, `scripts/probes/probe3_worker_crash.sh`
**Last changed:** Stage 4 iteration 1, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `repos.jobs.claim` | `(session, lease_seconds) -> Job \| None` | one `UPDATE jobs SET status='running', attempts+1, locked_until=now()+lease WHERE id = (SELECT … WHERE (pending AND run_at<=now()) OR (running AND locked_until<now()) ORDER BY run_at, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`; caller commits before running |
| `repos.jobs.renew` | `(session, id, lease)` | heartbeat: `locked_until=now()+lease WHERE id AND status='running'` |
| `repos.jobs.complete` | `(session, id)` | `done`, `locked_until`/`last_error` NULL |
| `repos.jobs.retry_or_fail` | `(session, id, error, delay, max) -> status` | one UPDATE with CASE: `attempts < max` → `pending`, `run_at=now()+delay`; else `failed`; stores `last_error` |
| `repos.jobs.enqueue` / `get` / `advance` | | insert (IntegrityError on the active-job index) / by id / dev clock: `run_at -= N` for pending, `locked_until -= N` for running |
| `services.jobs.schedule_campaign` | `(session, campaign_id, run_at \| None)` | 404 via `get_campaign`, enqueue + commit, IntegrityError → `Conflict` (409) |
| `services.jobs.publish_now` / `get_job` / `advance_time` | | `run_at=None` (DB `now()`) / `NotFound` / commit + count |
| `runner.run_once` | `(session_factory=SessionLocal) -> bool` | claim+commit, start heartbeat thread (own session, every `lease/3`), run `HANDLERS[kind]`, stop heartbeat, then complete or `retry_or_fail` with `publishing.backoff_seconds(attempts)`; logs claim + outcome (type names only) |
| `runner.HANDLERS` | `{kind: (session, payload)}` | `publish_campaign` → `publishing.publish_campaign(s, payload["campaign_id"])` |
| `__main__` | `python -m app.worker` | loops `run_once`; sleeps `WORKER_POLL_SECONDS` when idle; any loop exception is logged and survived |

## Connections
- Depends on: [[Publishing Service]], [[Data Model]] (`jobs`, migration 0003), [[Api Layer]] (settings)
- Used by: [[Api Layer]] (`/publish`, `/schedule`, `/jobs/{id}`, `/_dev/advance-time`) · map: [[System Map]] · contract: [[API]]

## Invariants
- At most one `pending`/`running` `publish_campaign` job per campaign: partial unique index `uq_jobs_active_campaign` on `((payload->>'campaign_id'))`. The DB enforces it, so concurrent enqueues cannot both win.
- A claim is committed before the handler runs; two workers never hold the same job (SKIP LOCKED).
- A killed worker's job is reclaimed once `locked_until` passes; re-running is safe because accepted entries are skipped and in-flight entries reuse their committed idempotency key.
- A live job's lease is renewed every `lease/3` s, so a job longer than the lease (Retry-After waits) is not reclaimed.
- `jobs.run_at` / `locked_until` are naive UTC (`timestamp without time zone`); the API converts aware input to UTC.

## Tests
- `tests/unit/test_jobs.py` — SKIP LOCKED concurrent claim, future job not claimed, expired vs live lease, handler error → pending later + `last_error`, then `failed` at `JOB_MAX_ATTEMPTS`, heartbeat keeps a 0.3 s lease alive for 0.6 s, `run_once` end-to-end publishes via a fake transport, schedule 202/404/409/422 (naive, garbage, out-of-range), past `run_at` runs at once, publish 202, `/jobs` 404/422, advance-time shifts pending + running / 422 / 404 when the flag is off, partial unique index
- `tests/unit/test_publishing.py::test_endpoint`, `::test_unexpected_error_fails_one_entry_and_continues` — now enqueue + `run_once`
- `scripts/probes/probe3_worker_crash.sh` (`make probe3`) — kill the worker mid-publish, restart, expire the lease: all jobs done, 8 posts, 1 per key

## Gotchas
- shortcut: a job reclaimed after repeated crashes is not capped (attempts only gate handler *exceptions*); add a claim-time `attempts > max → failed` if crash loops become real.
- The worker does not run migrations; started before the api has migrated, it logs `worker loop error: ProgrammingError` and recovers on the next poll.
- `/_dev/advance-time` also shifts live leases; with one worker that is harmless (heartbeat renews it), with several it could hand a live job to a second worker.
