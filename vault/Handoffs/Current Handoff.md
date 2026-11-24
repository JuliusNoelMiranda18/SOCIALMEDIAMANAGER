# Handoff — Stage 1: Fake platform server

**Goal:** a controllable simulator of Instagram/X.
**Stage start commit:** uncommitted (Stage 0 work is approved but not committed; HEAD is d0e1764)

## Context to read (only these)
- Vault: [[System Map]], [[API]], [[Api Layer]]
- Source: `fake_platform/main.py`, `app/config.py`, `docker-compose.yml`, `tests/`
- Run everything in containers (host Python is 3.9): `docker compose run --rm api pytest -q`, `... ruff check .`
- The stack may already be running. After code changes use `docker compose up -d --build --wait`.

## Design decisions (Senior, follow these)
- State is in-memory in the fake-platform process. `POST /_control/reset` clears posts, idempotency records, tokens and switches back to defaults.
- **Auth:** `POST /oauth/token` takes form fields `grant_type=client_credentials`, `client_id`, `client_secret`; returns `{"access_token","token_type":"Bearer","expires_in":3600}`. Wrong `grant_type` or missing fields → 400 (never 500). `POST /v1/posts` needs `Authorization: Bearer <issued token>`; missing/unknown → 401.
- **`POST /v1/posts`:** JSON `{"platform": "instagram"|"x", "caption": str, "image_url": str|null}` (Pydantic; invalid → 422). Header `Idempotency-Key` is required (missing → 400). Returns 201 `{"id","platform","status":"accepted"}`.
- **Order of checks:** auth → idempotency replay (known key returns the stored response with the same status, creates no post, sends no callback) → rate-limit mode → failure rate → accept.
- **Control switches** via `POST /_control` (partial update; `GET /_control` shows current):
  - `rate_limit`: `{enabled: bool, retry_after_seconds: int>=0}` → `POST /v1/posts` answers 429 with header `Retry-After: <seconds>`.
  - `failure_rate`: float 0..1 → that fraction of fresh posts answer 503 (use `random.random()`; 1.0 must always fail, 0.0 never). A failed request stores nothing.
  - `drop_response`: `{enabled: bool, delay_seconds: int}` → post IS stored and callback IS scheduled, but the response is delayed `delay_seconds` (default 30) so the client times out. A retry with the same key returns the stored response immediately.
  - `forged_signature`: bool → callbacks go out with a wrong signature.
  - `webhook_url`: str (default from env `WEBHOOK_URL`, default `http://api:8000/webhook/social-delivery`).
  - Invalid control values → 422.
- **`GET /_posts`:** list of stored posts (`id`, `platform`, `caption`, `image_url`, `idempotency_key`, `created_at`).
- **Callback:** after accepting a post (background task, never blocks or breaks the response), `POST` JSON `{"event_id","post_id","status":"delivered","platform","timestamp"}` to `webhook_url`. Signature = HMAC-SHA256 hex over `f"{timestamp}.{raw_body}"` with `WEBHOOK_SECRET` (shared secret from settings). Headers: `X-Timestamp` (unix seconds), `X-Signature` (hex). In forged mode send a wrong signature. If the webhook URL is unreachable (it will be until Stage 5), log a warning and carry on.
- Put the signing helper in a small function (`sign(secret, timestamp, body)`) so Stage 5 can reuse the exact scheme.
- Keep it one small module plus maybe a helper file. No speculative abstractions.

## Tasks — Iteration 1
| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 1 | Backend | Implement `/oauth/token`, `/v1/posts` with idempotency, `GET /_posts`, per the decisions above | `fake_platform/` | pytest: same key twice → 1 stored post, identical response; no auth → 401; missing key → 400 |
| 2 | Backend | Implement `/_control` (GET, POST, `/_control/reset`) with all five switches and validation | `fake_platform/` | pytest: each switch has a test; bad value → 422 |
| 3 | Backend | Signed callback sender + `sign()` helper; callback sending is a replaceable function so tests can capture it | `fake_platform/` | pytest: captured callback's signature verifies with `WEBHOOK_SECRET`; forged mode does NOT verify; unreachable webhook does not fail the post |
| 4 | Backend | Rate-limit test: 429 mode returns `Retry-After` header with the configured value and stores no post | `tests/` | pytest passes |
| 5 | Backend | Probe script `scripts/probes/fake_platform.sh` driving the live stack with curl: token, post, same key again, 429 mode, failure mode, drop mode (use `curl -m 2`), forged mode, `GET /_posts`; prints labelled results and a PASS/FAIL line per check, exits non-zero on failure; resets state at the end | `scripts/probes/` | `bash scripts/probes/fake_platform.sh` against the running stack → all PASS, exit 0 |
| 6 | Backend | Add `WEBHOOK_URL` to `.env.example` and settings for the fake platform (its own small settings class is fine); add `make probe` target | `.env.example`, `Makefile`, `fake_platform/` | `make lint` clean; `make test` green |
| 7 | Backend | Vault: new module note `vault/Modules/Fake Platform.md` (from the Module template), update `vault/Architecture/API.md` fake-platform table with every endpoint, update README run section with the probe | `vault/`, `README.md` | notes exist, links resolve |
| 8 | Frontend | none this stage | — | — |

## Stage 1 agent checks (Tester runs these, from PLAN.md)
- pytest for each switch; same key twice → exactly 1 stored post (also verify live via curl and `GET /_posts`)
- 429 mode returns `Retry-After` header (verify live)
- callback signature verifies with the shared secret, forged mode does not
- drop mode: client times out but the post exists, retry with same key returns it without a second post
- no 500s: bad grant_type, bad JSON, bad control values, unknown routes
- `ruff check .` clean, no secrets in repo (`git grep -iE "api_key|secret=" -- ':!*.example'`), `bash scripts/probes/fake_platform.sh` exits 0
- Stage exit: every switch demonstrable by curl

## Constraints
- ponytail standard. Do not commit. Do not edit `PLAN.md`, `CLAUDE.md`, `docs/design.md`.
- Money/token counts are integers; validation errors are 4xx, never 500.
- Write questions to Blockers instead of guessing.

## Blockers
_Agents write questions here instead of guessing._

## Backend report — Iteration 1
**Built (tasks 1-7):** `fake_platform/main.py` (token, posts with idempotency, `_posts`, `_control` GET/POST/reset, signed callback via replaceable `deliver()`), `fake_platform/signing.py` (`sign`), `tests/unit/test_fake_platform.py` (10 tests), `scripts/probes/fake_platform.sh`, `WEBHOOK_URL` in `.env.example` (also appended to local `.env`), `make probe`, vault notes (`Modules/Fake Platform.md`, `Architecture/API.md`), README.

**Commands:** `docker compose up -d --build --wait` ok; `make lint` -> All checks passed; `make test` -> 12 passed; `make probe` -> 22 PASS lines, exit 0; `git grep -iE "api_key|secret=" -- ':!*.example'` -> only PLAN.md/handoff text, no code hits.

**Notes for Tester:**
- Token endpoint parses the urlencoded body by hand (no `python-multipart` dependency added).
- Failed (429/503) requests store no idempotency record, so same-key retry is a fresh attempt.
- Unit tests monkeypatch `fake_platform.main.deliver`; no live callback test (webhook receiver arrives Stage 5, live callback just logs a warning).
- Containers copy code at build time: `docker compose build api` is needed before `make test` sees code changes.
- Not done: no live check that a callback reaches a real receiver; `.env` is gitignored? (I appended WEBHOOK_URL locally; `.env` is not in git status.)
## Frontend report — Iteration 1
## Tester — Iteration 1 — FAIL
| Check | Result | Evidence |
|---|---|---|
| Boot, health 200 | PASS | `docker compose up -d --build --wait` all Healthy; curl :8000/health and :9000/health -> `{"status":"ok"}` |
| ruff check | PASS | `All checks passed!` |
| ruff format --check | FAIL | `1 file would be reformatted` tests/unit/test_fake_platform.py:48 (ISSUE-002) |
| pytest + cov | PASS | `12 passed`; fake_platform/main.py 98% |
| Probe script | PASS | `bash scripts/probes/fake_platform.sh` all PASS, exit 0 |
| Same key -> 1 post (live) | PASS | 10 concurrent same-key requests all 201, `/_posts` length 1; sequential replay identical |
| 429 + Retry-After (live) | PASS | `HTTP/1.1 429`, `retry-after: 11`; replay of known key during 429 mode returns stored 201 |
| Drop mode | PASS | probe: curl exit 28, post exists, retry returns stored, no second post |
| failure_rate 1.0 / 0 | PASS | 20x 503 and 0 posts stored; 20x 201 at 0.0 |
| Callback signature (live, own receiver, HMAC recomputed with .env WEBHOOK_SECRET) | PASS | normal `sig_valid= True`; forged mode `sig_valid= False`; replay sent no extra callback |
| Auth edge cases | PASS | no/invalid/malformed Bearer -> 401; empty/missing key -> 400; reset invalidates tokens (401) |
| No 500s on bad input | FAIL | bad grant_type 400, bad JSON 422, bad types/negatives 422, unknown route 404, unknown key 422 all fine; `failure_rate: NaN` / `Infinity` -> 500 (ISSUE-003) |
| Reset clears state | PASS | posts `[]`, control defaults, token rejected after reset |
| Secret grep | PASS | `git grep -inE "api_key|secret=|token="` -> only handoff/PLAN text; no creds in logs |
Issues: [[ISSUE-002 ruff format fails on test_fake_platform]], [[ISSUE-003 failure_rate NaN or Infinity returns 500]]
Notes (non-blocking): nested partial update of rate_limit/drop_response resets sibling fields to defaults; same key + different body replays the first response (per design). Control switches reset to defaults at end.

<!-- Senior Dev appends "Tasks — Iteration 2" etc. on FAIL -->

## Tasks — Iteration 2
Senior triage of the Tester's FAIL (loop 2 of 3): ISSUE-002 and ISSUE-003 accepted. I also accept the Tester's non-filed note about nested partial updates, because the Stage 1 design says `/_control` is a partial update.

| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 9 | Backend | ISSUE-002: run `ruff format` on the repo, and make `make lint` also run `ruff format --check .` so this cannot slip again | `tests/unit/test_fake_platform.py`, `Makefile` | `make lint` → clean, includes the format check; `docker compose run --rm api ruff format --check .` → exit 0 |
| 10 | Backend | ISSUE-003: reject NaN/Infinity for `failure_rate` (and any other float/int control field) with 422, not 500. Add a regression test sending raw JSON `{"failure_rate": NaN}` and `{"failure_rate": Infinity}` | `fake_platform/main.py`, `tests/unit/test_fake_platform.py` | live: `curl -s -o /dev/null -w '%{http_code}' -X POST localhost:9000/_control -H 'content-type: application/json' -d '{"failure_rate":NaN}'` → 422; same for `Infinity` and `-Infinity`; state unchanged |
| 11 | Backend | Nested partial update: `{"rate_limit":{"enabled":false}}` must keep the existing `retry_after_seconds` (merge nested objects, same for `drop_response`). Add a test | `fake_platform/main.py`, `tests/unit/test_fake_platform.py` | pytest: set retry_after 11, then send `{"rate_limit":{"enabled":false}}` → GET /_control shows retry_after_seconds still 11 |
| 12 | Backend | Close ISSUE-002 and ISSUE-003 in `vault/Issues/` (status closed, link the fix); update `Fake Platform` module note if behaviour changed | `vault/Issues/`, `vault/Modules/Fake Platform.md` | notes updated |

Reminder: rebuild before testing (`docker compose up -d --build --wait`), containers copy code at build time. Do not commit.

## Backend report — Iteration 2
**Done (tasks 9-12):**
- 9: `ruff format` applied to `tests/unit/test_fake_platform.py`; `make lint` now runs `ruff check . && ruff format --check .` (Makefile).
- 10: `fake_platform/main.py`: `allow_inf_nan=False` on `failure_rate` (Control and ControlUpdate), plus a `RequestValidationError` handler that drops the echoed `input`. The flag alone still gave 500, because the default 422 body echoes the NaN and cannot be JSON-encoded. 3 regression tests (NaN, Infinity, -Infinity).
- 11: nested partial update now merges (`model_dump(exclude_unset=True)` + `model_copy(update=...)`); test for `rate_limit` and `drop_response`.
- 12: ISSUE-002 and ISSUE-003 closed with a fix section, index updated, `Fake Platform` note updated.

**Commands:**
- `docker compose up -d --build --wait` -> all Healthy
- `make lint` -> `All checks passed!` / `26 files already formatted`
- `docker compose run --rm api ruff format --check .` -> exit 0 (26 files already formatted)
- `make test` -> `16 passed`
- live `curl -X POST :9000/_control -d '{"failure_rate":X}'` for NaN, Infinity, -Infinity -> 422, 422, 422; `GET /_control` shows `failure_rate` 0.0
- `make probe` -> exit 0

**Tester focus:** `detail` in 422 bodies no longer includes `input` or `ctx` (all endpoints). Same key with a different body still replays the first response (per design).

## Tester — Iteration 2 — PASS
| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Rebuild/boot | PASS | `docker compose up -d --build --wait` all Healthy |
| ruff check / format --check (ISSUE-002) | PASS | `All checks passed!` / `26 files already formatted`; `make lint` runs both |
| make test | PASS | `16 passed` |
| make probe | PASS | all PASS lines, exit 0 |
| NaN/Infinity/-Infinity (ISSUE-003) | PASS | live POST /_control -> HTTP 422 x3, body `{"detail":[{"loc":["body","failure_rate"],"msg":"Input should be a finite number","type":"finite_number"}]}`; GET /_control unchanged (failure_rate 0.0) |
| Nested partial update | PASS | set retry 11 + drop delay 5; `{"rate_limit":{"enabled":false}}` -> retry_after_seconds 11; `{"drop_response":{"enabled":true}}` -> delay_seconds 5 kept |
| 422 bodies useful + valid JSON | PASS | /_control: loc `["body","failure_rate"]`, extra_forbidden `["body","bogus"]`, json_invalid; /v1/posts: literal_error on platform, string_type on caption, missing body; no `input`/`ctx` leaked; /oauth/token bad input -> 400 `invalid_request` |
| Same key twice -> 1 post | PASS | both 201 identical id; /_posts length 1 |
| 429 Retry-After | PASS | `HTTP/1.1 429`, `retry-after: 9` |
| Drop mode | PASS | in probe (curl exit 28, post exists, retry returns stored, no 2nd post) |
| Callback signature (own HMAC recompute, own receiver) | PASS | normal `sig_valid= True`; forged `sig_valid= False` |
| failure_rate 1.0 | PASS | 503 x3, /_posts `[]` |
| No 500s | PASS | bad JSON, empty body, array body, wrong types, unknown route 404, bad token body 400 |
| Secret grep | PASS | `git grep -inE "api_key|secret=|token="` outside examples/docs: no hits; no secrets in fake-platform logs |
Issues: none new. [[ISSUE-002 ruff format fails on test_fake_platform]] and [[ISSUE-003 failure_rate NaN or Infinity returns 500]] verified fixed. Control switches reset to defaults.
