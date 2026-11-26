# Handoff — Stage 5: Signed webhook + status tracking

**Goal:** status is trust. Only a verified platform callback marks an entry `published`.
**Stage start commit:** `55a2a03`

## Context to read (only these)
- Vault: [[System Map]], [[Publishing Service]], [[Data Model]], [[Api Layer]], [[Fake Platform]], [[Worker]], [[API]], [[ADR-002 Publish flow]]
- Source: `fake_platform/main.py` (`send_callback`, `Control.forged_signature`), `fake_platform/signing.py` (`sign`), `app/models.py` (`WebhookEvent`, `SocialPostEntry`), `app/repos/campaigns.py` (`mark_accepted`), `app/services/jobs.py` (`schedule_campaign`), `app/api/routes.py`, `app/api/schemas.py`, `app/main.py` (body limit, error handlers), `app/config.py`, `scripts/make_env.py`, `scripts/probes/_stage3_lib.sh`, `scripts/probes/probe1_idempotency.sh`, `Makefile`

## What the fake platform already sends (do not change the scheme)
`POST WEBHOOK_URL`, raw JSON body `{"event_id": uuid, "post_id": <platform post id>, "status": "delivered", "platform": "...", "timestamp": <int>}`, headers `X-Timestamp: <int>` and `X-Signature: hex(HMAC-SHA256(WEBHOOK_SECRET, "<X-Timestamp>.<raw body>"))`. Forged mode sends 64 zeros. It is sent as a background task right after the 201, so it can arrive **before** the worker has written `platform_post_id`. It is never retried.

## Design (decided — do not redesign)
- **Route** `POST /webhook/social-delivery`. Read the **raw** body (`await request.body()`) and verify it before parsing JSON.
- **Verify** (in `app/services/webhooks.py`, a pure function plus small helpers):
  1. Both headers present, and `X-Timestamp` is an int, else 400.
  2. `abs(now - ts) <= WEBHOOK_TOLERANCE_SECONDS` (300, setting) in both directions, else 400 (`stale timestamp`).
  3. Compute `sign(secret, ts, raw)` and compare with `hmac.compare_digest` (constant time), else 400. Reuse `fake_platform/signing.py::sign`, or copy its one line into `app/`; your choice, but the app must not import the fake platform's FastAPI app.
  4. Only then parse the JSON: bad JSON or missing/invalid fields (`event_id` non-empty str ≤200, `post_id` str, `status` in `{"delivered","failed"}`) → 400. Body `timestamp` ≠ header → 400.
  - Every rejection → 400 with a short reason, **no DB writes**, and one log line with the reason only (no secret, no signature).
- **Dedupe:** `INSERT INTO webhook_events (event_id, raw_body, signature_valid, platform_post_id, status) … ON CONFLICT (event_id) DO NOTHING RETURNING id`. No row back → duplicate → 200 `{"result":"duplicate"}`, nothing else changes. Only **verified** events are stored, so a forged request can never use up a real `event_id`.
- **Apply** in the same transaction as the insert, as a conditional SQL update (the Stage 3 pattern):
  - `delivered` → `UPDATE social_post_entries SET status='published' WHERE platform_post_id=:pid AND status='publishing'`
  - `failed` → `… SET status='failed', last_error='platform reported failure' WHERE platform_post_id=:pid AND status='publishing'`
  - Response 200 `{"result":"applied"}` if a row changed, else `{"result":"unmatched"}`. A verified event for an unknown post or an already-terminal entry is still stored and still answered 200.
- **Early-callback race:** `mark_accepted` must also check for a stored event. Set `status = CASE WHEN EXISTS (SELECT 1 FROM webhook_events WHERE platform_post_id=:pid AND status='delivered') THEN 'published' ELSE 'publishing' END` (and the same for `failed`, if simple). So the entry ends `published` whichever arrives first. Keep "acceptance always wins over a failure" otherwise.
- **State machine** `draft → queued → publishing → published | failed`:
  - Enqueueing a publish job (`schedule_campaign`) sets the campaign's entries `draft → queued` (conditional: only `draft`; same transaction as the job insert).
  - `published` never regresses: no webhook, worker or retry write may move it. Audit every write in `app/repos/campaigns.py` and add `AND status <> 'published'` wherever one could. `publish_campaign` already skips `published`.
  - `failed` stays retryable by an explicit publish (Stage 3 behaviour). Write that down in [[Publishing Service]] as the one allowed exit from `failed`.
- **Migration `0004_webhooks`:** `webhook_events` + `platform_post_id text` (indexed) + `status text`. Downgrade drops them. Update `WebhookEvent`.
- **Secret:** `scripts/make_env.py` also fills `WEBHOOK_SECRET` with `secrets.token_hex(32)` when it is empty or `changeme-placeholder`, and never replaces a real one. Run `make env` so the local `.env` gets a real secret (api and fake-platform both read it). `.env.example` keeps the placeholder. Add `WEBHOOK_TOLERANCE_SECONDS=300` to `app/config.py` and `.env.example`.

## Tasks — Iteration 1
| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 1 | Backend | Migration 0004 + model | `migrations/versions/0004_webhooks.py`, `app/models.py` | `alembic downgrade 0003 && upgrade head` → `0004 (head)` |
| 2 | Backend | Verify + dedupe + apply; route; settings; `make_env` secret | `app/services/webhooks.py`, `app/repos/webhooks.py`, `app/api/routes.py`, `app/config.py`, `.env.example`, `scripts/make_env.py`, `.env` (via `make env`) | unit tests below; `make env` prints that it wrote a webhook secret once, and "already set" on a second run |
| 3 | Backend | `queued` on enqueue; `mark_accepted` race fix; no-regress guards on `published` | `app/services/jobs.py`, `app/repos/jobs.py` or `app/repos/campaigns.py` | unit tests below |
| 4 | Backend | **Probe 4** `scripts/probes/probe4_webhook.sh` + `make probe4`. (a) Fake platform reset, `forged_signature` on, publish a 2-platform campaign, wait for the job `done`, sleep 3 s → both entries `publishing` with a post id, `webhook_events` count unchanged. (b) Forged off, publish a new campaign → both `published` within 15 s. (c) The probe signs its own event with `WEBHOOK_SECRET` (read it via `docker compose exec -T api python -c …`; never echo it) for a `publishing` entry: POST it twice → `applied`, then `duplicate`; one `webhook_events` row. (d) Valid signature but timestamp now−600 → 400. (e) Signed body then one byte changed → 400. (f) A `failed` event for an already `published` entry → stays `published`. | `scripts/probes/probe4_webhook.sh`, `Makefile` | `make probe4` → ALL PASS |
| 5 | Backend | Keep regression green: `probe1` line 10 expects `{'publishing'}` right after publish; now the webhook makes it `published`. Change it to accept `published` (the callback is the point of this stage). Check the other probes for the same assumption. | `scripts/probes/probe1_idempotency.sh`, others only if needed | `make probe probe5 probe1 probe2 probe6 probe3` → ALL PASS |
| 6 | Backend | Unit tests `tests/unit/test_webhooks.py`: valid → published; forged / missing headers / non-int ts / stale past / stale future / modified body / bad JSON / bad status / ts mismatch → 400 and no row; duplicate → `duplicate` and processed once; a verified event before `mark_accepted` → entry ends `published`; `failed` event on `published` → unchanged; unknown post id → `unmatched` 200; enqueue → `queued`; constant-time compare used (`hmac.compare_digest` patched/spied or code-asserted). | `tests/unit/test_webhooks.py`, existing tests if needed | `make up && make test && make lint` → green |
| 7 | Backend | Vault: new [[Webhook]] module note (`vault/Modules/Webhook.md`); update [[Publishing Service]] (state machine, the race fix), [[Data Model]] (0004), [[Api Layer]], [[API]], [[System Map]] (the arrow is already there; mark it built). | `vault/Modules/*`, `vault/Architecture/*` | notes cover every changed file |

## Out of scope
- No fake-platform retry of callbacks, no UI, no changes to `publish_campaign`'s retry loop.

## Blockers
_Agents write questions here instead of guessing._

## Backend report — Iteration 1
**Files changed**
- New: `migrations/versions/0004_webhooks.py`, `app/services/webhooks.py`, `app/repos/webhooks.py`, `tests/unit/test_webhooks.py`, `scripts/probes/probe4_webhook.sh`
- Changed: `app/models.py` (`WebhookEvent.platform_post_id/status`, both `platform_post_id` indexed), `app/repos/campaigns.py` (`mark_queued`, `apply_delivery`, `mark_accepted` race fix, `status <> 'published'` on `mark_accepted` / `record_error` / `mark_publishing`), `app/services/jobs.py` (`mark_queued` in the job-insert transaction), `app/api/routes.py` (`POST /webhook/social-delivery`), `app/config.py` + `.env.example` (`WEBHOOK_TOLERANCE_SECONDS=300`), `scripts/make_env.py` (WEBHOOK_SECRET), `scripts/probes/probe1_idempotency.sh` (line 10), `Makefile` (`probe4`)
- `.env`: `make env` wrote a real WEBHOOK_SECRET (value never printed). Second run: `already set`.
- Vault: new [[Webhook]], [[DE-001 set literals in probe jget expressions]]; updated [[Publishing Service]] (state machine, race fix, the one exit from `failed`), [[Data Model]] (0004), [[Api Layer]], [[Fake Platform]], [[API]], [[System Map]] (arrow marked built), [[00 Home]] map link.

**Decisions**
- `webhook_events` already existed (0001), so 0004 adds `platform_post_id` + `status` + index on them, plus an index on `social_post_entries.platform_post_id` (the webhook's lookup). Downgrade drops those four things, not the table.
- `sign` is copied into `app/services/webhooks.py` and works on raw bytes; a unit test asserts it equals `fake_platform/signing.py::sign`.
- Body validated by a small Pydantic model (strict types, no NUL in strings so Postgres cannot 500). `X-Timestamp` must match `[0-9]{1,12}` (so `1_000`, `+5`, ` 5` are 400). Signature compared as bytes (`compare_digest` on str raises on non-ASCII).
- Route is `async` (needs `await request.body()`) and runs the sync DB work via `run_in_threadpool`.
- `mark_accepted` handles both early `delivered` (→ published) and early `failed` (→ failed + `last_error`).

**How to run:** `make env && make up`, then `make probe4`.

**Commands run (final pass, once each)**
- `alembic downgrade 0003 && alembic upgrade head && alembic current` (in api) → `0004 (head)`
- `make env` ×2 → `wrote a fresh WEBHOOK_SECRET`, then `WEBHOOK_SECRET already set`
- `make up` → `Container socialmediamanager-api-1 Healthy` (exit 0)
- `make test` → `298 passed, 2 warnings in 39.95s`
- `make lint` → `All checks passed!` / `72 files already formatted`
- `make probe4` → 15 × PASS, `ALL PASS`
- `make probe probe5 probe1 probe2 probe6 probe3` → each prints `ALL PASS` (fake_platform.sh ends `PASS reset clears posts`), exit 0, 0 `FAIL` lines. **But** probe1 printed two Python tracebacks behind a false PASS on line 10: my first edit used a `{a,b}` set literal, which macOS bash 3.2 brace-expands (see DE-001). Fixed to `all(… in ('publishing', 'published') …)`; re-ran `make probe1` alone → `ALL PASS`, 0 tracebacks.

**Tester focus**
- Race gap (documented in [[Publishing Service]]): if the webhook's UPDATE runs before the worker's `mark_accepted` row write and its commit lands after `mark_accepted`'s EXISTS snapshot, the entry stays `publishing`. Very narrow; not covered by a test.
- `make probe1` under `bash` (not zsh) — confirm no tracebacks.
- The api accepts the placeholder secret if `.env` was never run through `make env` (no startup refusal; not asked for).
- Logs: `docker compose logs api | grep "webhook rejected"` shows reasons only.

## Tester — Iteration 1 — FAIL
| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Boot | PASS | `make up` → api, worker, db, web, fake-platform `Healthy` |
| Unit tests | PASS | `make test` → `298 passed, 2 warnings in 43.03s` (before the new race test was added) |
| Lint | PASS | `make lint` → `All checks passed!` / `72 files already formatted`; new test file also clean |
| Probe 4 (forged → 400 unchanged, valid → published, duplicate once, stale 400, tamper 400, no regress) | PASS | `make probe4` → 15 × PASS, `ALL PASS` |
| Regression probes | PASS | `make probe probe5 probe1 probe2 probe6 probe3` → exit 0; 5 × `ALL PASS` + `PASS  reset clears posts`; 0 `FAIL`, 0 `Traceback`/`Error` lines; probe1 line 10 `PASS  status publishing or published` |
| Bad input on webhook route (15 cases) | PASS | `bash scripts/probes/probe4_bad_inputs.sh` → no headers / non-int / 40-digit / negative ts / non-ASCII / empty sig / signed non-JSON / invalid UTF-8 / array / NUL / bad status / 201-char id / string ts / future +600 / 2 MB → all 400; `no webhook_events rows stored (54 -> 54)`; `ALL PASS` |
| Secrets / logs | PASS | `docker compose logs api \| grep "webhook rejected"` → reasons only (`invalid body`, `stale timestamp`); 0 log lines with the secret, the signature or `X-Signature`; secret not in git; `.env` ignored |
| Code review: raw body verified before parse, `hmac.compare_digest`, rejection writes nothing, forged never stored, `published` never regresses | PASS | `verify()` checks headers → ts → `compare_digest` (bytes) → only then `model_validate_json`; `handle` raises before any session use; `NOT_PUBLISHED` on `mark_accepted`/`record_error`/`mark_publishing`, `apply_delivery` only moves `publishing`; dedupe via `ON CONFLICT (event_id) DO NOTHING` (unique constraint, not read-then-write) |
| **Race webhook vs `mark_accepted`** | **FAIL** | `docker compose run --rm api pytest -q tests/acceptance/test_stage5_race.py` → `assert 'publishing' == 'published'` at lines 68 and 79, `2 failed`. Both interleavings reproduce; entry stuck `publishing` forever with a verified `delivered` event stored |

Issues: [[ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing]]

Notes
- New tester files: `scripts/probes/probe4_bad_inputs.sh` (re-runnable), `tests/acceptance/test_stage5_race.py` (red until ISSUE-010 is fixed, so `make test` is now red: 2 failed). Code is baked into the api image (no bind mount), so rebuild (`make up`) before running new tests.
- Minor, not blocking: a 2 MB signed body gets 400 (`invalid body`), not 413 — acceptable per handoff (400 or 413). `signature_valid` is always `True` now (only verified events are stored); harmless.

## Tasks — Iteration 2
Tester FAIL on [[ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing]]. Everything else passed; change nothing else.

| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 1 | Backend | Serialize the two writers per platform post id. As the **first statement** of the webhook's DB transaction (before the dedupe insert) and of `mark_accepted`'s transaction (before its UPDATE), run `SELECT pg_advisory_xact_lock(hashtext(:platform_post_id))`. Under READ COMMITTED, the next statement takes a fresh snapshot after the lock is granted, so whichever writer goes second sees the other's commit. The lock is released at commit/rollback; no unlock call. Keep `mark_accepted`'s existing caller-commits contract; the lock just has to be in the same transaction as the write. Add a one-line comment at each site naming ISSUE-010. | `app/repos/webhooks.py`, `app/repos/campaigns.py` (and the service only if the transaction boundary needs it) | `make up && docker compose run --rm api pytest -q tests/acceptance/test_stage5_race.py` → `2 passed` |
| 2 | Backend | Keep the tester's `tests/acceptance/test_stage5_race.py` as the regression test (do not weaken it). Update [[Webhook]] + [[Publishing Service]] notes: remove the "race gap" gotcha, describe the lock. Mark ISSUE-010 fixed (status line) with the fix. | vault notes, `vault/Issues/ISSUE-010 …` | notes updated |
| 3 | Backend | Quick regression | — | `make test` all green, `make lint` clean, `make probe4 probe1` ALL PASS |

## Backend report — Iteration 2
**Files changed**
- `app/repos/webhooks.py` — `store` runs `SELECT pg_advisory_xact_lock(hashtext(:p))` first (it is the first DB statement of the webhook request's transaction in `handle`).
- `app/repos/campaigns.py` — `mark_accepted` runs the same lock before its UPDATE (first statement after `take_attempt`'s commit; caller-commits contract unchanged). Both sites comment ISSUE-010.
- Vault: [[Webhook]], [[Publishing Service]] (race gap removed, lock described), ISSUE-010 status `fixed` + Resolution, `_Issues Index` row `fixed`.
- Service layer untouched; race test untouched.

**How to run:** `make up && docker compose run --rm api pytest -q tests/acceptance/test_stage5_race.py`

**Commands run**
```
$ make up                      -> all containers Healthy
$ docker compose run --rm api pytest -q tests/acceptance/test_stage5_race.py
2 passed, 1 warning in 2.98s
$ make test
300 passed, 2 warnings in 21.69s
$ make lint
All checks passed!
73 files already formatted
$ make probe4 probe1
... PASS  failed event on published entry: unmatched
PASS  entry stays published
ALL PASS                       (probe4)
... PASS  x: exactly 1 post despite the timeout
PASS  4 posts in total
ALL PASS                       (probe1)
```

**Tester focus:** the lock lives in the repo functions (the race test calls them directly), so any other future caller of `store`/`mark_accepted` gets it too. `hashtext` collisions only cause extra waiting, never wrong results. No new unit test: the acceptance race test is the regression test.

## Tester — Iteration 2 — PASS
| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Diff review | PASS | `git diff -- app/repos/webhooks.py app/repos/campaigns.py`: `SELECT pg_advisory_xact_lock(hashtext(:p))` is the first statement of `store` (first DB statement in `handle`'s txn) and of `mark_accepted` (first after `take_attempt`'s commit), both comment ISSUE-010; no other behaviour change |
| Boot | PASS | `make up` → api, worker, db, web, fake-platform Healthy |
| ISSUE-010 repro | PASS | `docker compose run --rm api pytest -q tests/acceptance/test_stage5_race.py` → `2 passed, 1 warning in 2.86s` |
| Unit + acceptance | PASS | `make test` → `300 passed, 2 warnings in 25.36s` |
| Lint / format | PASS | `make lint` → `All checks passed!` / `73 files already formatted` |
| probe4 (webhooks) | PASS | `failed event on published entry: unmatched`, `entry stays published`, `ALL PASS` |
| probe1 (idempotency) | PASS | `x: exactly 1 post despite the timeout`, `4 posts in total`, `ALL PASS` |
| probe3 (killed worker) | PASS | `killed mid-run`, jobs 86–89 done, `8 posts in total`, `ALL PASS` |

Note: probes were run a second time only to count FAIL lines (`grep -c FAIL` → 0); not a flake re-run.
Issues: [[ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing]] → verified. No new issues.
