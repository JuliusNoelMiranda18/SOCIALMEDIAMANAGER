# Handoff — Stage 3: Adapters, idempotent publish, rate limits, encrypted tokens

**Goal:** the heart of the grade. Publishing is idempotent, rate-limit aware, and tokens are encrypted at rest.
**Stage start commit:** uncommitted (Stages 0–2 approved but not committed; HEAD is d0e1764)

## Context to read (only these)
- Vault: [[System Map]], [[API]], [[ADR-002 Publish flow]] (**read first, it fixes the design**), [[Data Model]], [[Fake Platform]], [[Api Layer]]
- Source: `app/models.py`, `app/config.py`, `app/main.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/services/campaigns.py`, `app/repos/campaigns.py`, `fake_platform/main.py`, `migrations/versions/0001_initial.py`, `.env.example`, `Makefile`, `tests/conftest.py`
- Run everything in containers (host Python is 3.9). Rebuild after code changes: `docker compose up -d --build --wait`.

## Design decisions (Senior, follow these; see ADR-002)

### Interface and adapters (`app/publishers/`)
- `SocialPublisher` is a `typing.Protocol` with one method: `publish(req: PublishRequest) -> PublishOutcome`.
  - `PublishRequest`: `platform, caption, image_url, idempotency_key`.
  - `PublishOutcome` (one small dataclass or a few): `accepted(platform_post_id)`, `rate_limited(wait_seconds)`, `retryable(reason)`, `fatal(reason)`.
- `FakeInstagramPublisher` and `FakeXPublisher` talk to the fake platform over `httpx` (base `FAKE_PLATFORM_URL`). They share one small helper for the HTTP call; each class only adds what differs (platform name; Instagram requires an image; X caption ≤280 → `fatal` if violated). No class hierarchy beyond that.
- Each adapter makes **exactly one** HTTP attempt per `publish()` call. Mapping: 201 → accepted; 429 → rate_limited with wait from `Retry-After` (integer seconds **or** HTTP-date, parse both; missing/garbage → treat as retryable with backoff); 5xx, timeout, connection error → retryable; 401 → refresh the token once and retry that same attempt; other 4xx → fatal.
- One factory `get_publisher(platform) -> SocialPublisher`. Services import only the protocol and the factory, never an adapter class (test enforces it by grepping `app/services/`).

### Tokens (`app/crypto.py`, `app/publishers/tokens.py`)
- AES-GCM (`cryptography`), 12-byte random nonce per encryption, AAD = platform name. Stored in `platform_tokens` (`nonce`, `ciphertext`).
- `TOKEN_ENCRYPTION_KEY` = base64 of 32 random bytes. Validate when the **api** starts (fail fast with a clear message); do NOT validate inside the shared `Settings` class, because `fake_platform` imports it too.
- `.env.example`: `TOKEN_ENCRYPTION_KEY=` left empty with a comment; add `make env` that creates `.env` from `.env.example` if missing and fills a fresh random key (python `secrets` + base64). Update your local `.env` the same way. README: first-run step becomes `make env && make up`.
- Getting a token: read from `platform_tokens` and decrypt; if missing, call fake platform `/oauth/token` with `FAKE_CLIENT_ID` / `FAKE_CLIENT_SECRET` (placeholders in `.env.example`), encrypt, store. On 401, fetch a new token, replace the row, retry once.
- **Never log a token or the Authorization header.** No `repr` of objects that hold the token. Test: capture logs during a publish and assert the token string is absent.

### Publish service (`app/services/publishing.py`)
- `publish_campaign(session, campaign_id, *, sleep=time.sleep)` publishes every entry that is not already `published` or `publishing`-with-`platform_post_id` set (those are no-ops, so publishing twice is safe).
- Per entry: if `idempotency_key` is null, set it per ADR-002, set `status='publishing'`, **commit**, then call the publisher. Retry loop: max `PUBLISH_MAX_ATTEMPTS` (default 5); on rate_limited wait exactly `max(Retry-After, backoff)`; on retryable wait exponential backoff with full jitter (`BACKOFF_BASE_MS` 500, `BACKOFF_CAP_MS` 30000); if a Retry-After exceeds `MAX_RETRY_AFTER_SECONDS` (default 60) stop and mark failed with that reason. `sleep` is injectable so tests run instantly.
- Record `attempts` and `last_error` on the entry. Accepted → store `platform_post_id`, keep `status='publishing'` (Stage 5 flips it to `published` on a verified webhook). Fatal or attempts exhausted → `status='failed'`.
- `image_url` sent to the platform is absolute: `PUBLIC_BASE_URL` (default `http://api:8000`) + `/media/<file>`.
- HTTP timeout `PUBLISH_TIMEOUT_SECONDS` (default 5).

### Migration `0002_publish`
- `social_post_entries`: add `idempotency_key` (text, unique, nullable), `attempts` int not null default 0, `last_error` text nullable. Downgrade drops them.

### Endpoint
- `POST /campaigns/{id}/publish` → 200 with the campaign and entries (now including `status`, `attempts`, `last_error`, `platform_post_id`). Unknown campaign → 404. Runs synchronously (Stage 4 moves it to the worker). Update `API.md`.

### Fake platform additions (only what the probes need)
- `rate_limit.count`: optional int; when set, only the next N fresh posts get 429, then the switch turns itself off.
- `rate_limit.format`: `"seconds"` (default) or `"http-date"` for the `Retry-After` header.
- `GET /_stats` → `{"post_requests": [{"at": <iso>, "idempotency_key": ..., "status": <int>}...]}` recording every `POST /v1/posts`; cleared by `/_control/reset`.
- `GET /_tokens` → list of issued access tokens (dev-only, so probe 6 can grep for them).
- Keep Stage 1 behaviour and its probe green.

## Tasks — Iteration 1
| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 1 | Backend | Migration `0002_publish` + model fields | `app/models.py`, `migrations/versions/` | upgrade/downgrade/upgrade ok; `alembic check` no drift |
| 2 | Backend | `app/crypto.py` AES-GCM + startup key validation + `make env` + `.env.example`/README | `app/crypto.py`, `app/main.py`, `Makefile`, `.env.example`, `README.md` | pytest: round trip; tamper with ciphertext/nonce/AAD → error; two encryptions of the same token differ; bad key → api refuses to start with a clear message |
| 3 | Backend | Protocol, two adapters, factory, token store | `app/publishers/` | pytest with `httpx.MockTransport`: 201/429 (seconds and HTTP-date)/missing Retry-After/503/timeout/401-then-ok/400 mapped correctly; one HTTP request per `publish()` (plus at most one token refresh) |
| 4 | Backend | Publish service with retry loop + `POST /campaigns/{id}/publish` | `app/services/publishing.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/repos/` | pytest with fake sleep: key committed before the first call (assert from a second session inside the mocked transport); waits honour Retry-After; backoff grows and is capped; attempts exhausted → failed; publishing twice sends no second post; services import no adapter class |
| 5 | Backend | Fake platform additions (`count`, `format`, `/_stats`, `/_tokens`) | `fake_platform/main.py`, `tests/unit/test_fake_platform.py` | pytest; `make probe` still all PASS |
| 6 | Backend | Probes: `scripts/probes/probe1_idempotency.sh` (publish twice + drop-mode timeout then retry → exactly 1 post per platform in `/_posts`), `probe2_rate_limit.sh` (429 ×2 with Retry-After 2 → published on 3rd request, gap between requests ≥2 s, exactly 3 requests per entry in `/_stats`; also once with `format: http-date`), `probe6_tokens.sh` (`pg_dump` + `docker compose logs api worker` grep for every token from `/_tokens` → none found; ciphertext present). Make targets `probe1`, `probe2`, `probe6`. Each resets fake platform state and uses a short `PUBLISH_TIMEOUT` vs drop delay so it runs in under a minute. | `scripts/probes/`, `Makefile` | each exits 0 with all PASS |
| 7 | Backend | Vault: module notes `Publisher Adapters` and `Token Crypto` (names already used in [[System Map]]), new `Publishing Service` note or a section in an existing one, update [[System Map]], [[API]], [[Fake Platform]], [[Data Model]]; link every new note per the Linking rules in [[00 Home]] | `vault/` | notes exist and link both ways |
| 8 | Frontend | none this stage | — | — |

## Stage 3 agent checks (Tester runs these, from PLAN.md)
- probe 1: publish twice + retry after simulated timeout → exactly 1 post per platform
- probe 2: 429 `Retry-After` honoured (seconds and HTTP-date), no hammering — count requests and measure gaps
- probe 6: DB dump + logs contain no plaintext token; ciphertext differs per encryption
- idempotency key is stored before the network call (prove it, e.g. kill/timeout mid-call and inspect the row)
- app code depends on `SocialPublisher` only (grep services/api for adapter imports)
- no 500s on bad input to the new endpoint (bad ids, unknown campaign, publishing an already-published campaign)
- regression: `make lint`, `make test`, `make probe`, `make probe5`, `bash scripts/probes/stage2_tester.sh`, secret grep (`git grep -iE "api_key|secret=" -- ':!*.example'`; no real key in `.env.example`)
- Stage exit: probes 1, 2, 6 green

## Constraints
- ponytail standard. Do not commit. Do not edit `PLAN.md`, `CLAUDE.md`, `docs/design.md`, or ADR-001/ADR-002 (raise a Blocker if you disagree with them).
- Integers for counts/money; validation errors are 4xx, never 500. Tokens never logged.
- Write questions to Blockers instead of guessing.

## Blockers
_Agents write questions here instead of guessing._

## Backend report — Iteration 1
**Status:** tasks 1–7 done. Nothing committed.

### Files
- New: `app/crypto.py`, `app/publishers/__init__.py` (protocol, `PublishRequest`, `PublishOutcome`, `get_publisher`), `app/publishers/fake.py` (two adapters, shared `_send`, `retry_after_seconds`), `app/publishers/tokens.py` (`get_token`), `app/repos/tokens.py`, `app/services/publishing.py`, `migrations/versions/0002_publish.py`, `scripts/make_env.py`, `scripts/probes/_stage3_lib.sh`, `probe1_idempotency.sh`, `probe2_rate_limit.sh`, `probe6_tokens.sh`, `tests/unit/test_crypto.py`, `test_publishers.py`, `test_publishing.py`
- Changed: `app/models.py` (3 entry columns), `app/config.py` (key default `""` + Stage 3 settings), `app/main.py` (key check at import → `SystemExit`), `app/api/routes.py` + `schemas.py` (publish endpoint; `EntryOut` + `attempts`, `last_error`, `platform_post_id`), `fake_platform/main.py` (`count`, `format`, `/_stats` middleware, `/_tokens`), `tests/conftest.py` (fixed test key + client creds), `tests/unit/test_fake_platform.py`, `pyproject.toml` (+`cryptography`), `Makefile` (`env`, `probe1/2/6`), `.env.example`, `README.md`
- Vault: new [[Publisher Adapters]], [[Token Crypto]], [[Publishing Service]]; updated [[System Map]], [[API]], [[Fake Platform]], [[Data Model]], [[Api Layer]], [[00 Home]]
- Local `.env`: placeholder key replaced via `make env`; added `FAKE_CLIENT_ID`/`FAKE_CLIENT_SECRET` placeholders.

### How to run
`make env && make up`, then `make probe1 probe2 probe6`. `curl -X POST localhost:8000/campaigns/<id>/publish`.

### Commands and results
- `docker compose exec -T api sh -c "alembic downgrade 0001 && alembic upgrade head && alembic downgrade base && alembic upgrade head && alembic check"` → exit 0, `No new upgrade operations detected.`, current `0002 (head)`
- `make lint` → `All checks passed!` / `60 files already formatted`
- `make test` → `233 passed, 2 warnings` (warnings pre-existing: starlette httpx deprecation, PIL bomb warning in a test)
- `make probe1` → 12/12 PASS, `ALL PASS`, 12.9 s (includes "key stored + committed before the call returned": row checked via psql 2 s into a dropped-response publish)
- `make probe2` → `ALL PASS`, 11.3 s; gaps seconds `[2.04, 2.03]`, http-date `[2.45, 3.0]`; statuses `[429, 429, 201]` each
- `make probe6` → 8/8 PASS, `ALL PASS`, 2.0 s
- `make probe` → 21 PASS, no FAIL; `make probe5` → `ALL PASS`; `bash scripts/probes/stage2_tester.sh` → `ALL PASS` (see note 1)
- `docker compose run --rm --no-deps -e TOKEN_ENCRYPTION_KEY=changeme-placeholder api uvicorn app.main:app` → `api refuses to start: TOKEN_ENCRYPTION_KEY must be base64 of 32 random bytes; run \`make env\` to create one`
- `curl -X POST localhost:8000/campaigns/999/publish` → 404 `{"detail":"campaign not found"}`; `/campaigns/abc/publish` → 422
- Secret grep → only pre-existing hits (PLAN/EVIDENCE/handoff quoting the command, `gemini_api_key` setting, tests); none from Stage 3 files.

### Notes for the Tester
1. My migration round trip (`downgrade base`) wiped the dev DB but not `./media`, so new campaign ids collided with stale PNGs and `stage2_tester.sh`'s fault symlink failed (`ln: media/81_x.png: File exists`). I deleted the 61 stale `media/<id>_*.png` files with id above `max(campaigns.id)`; it then passed. Not a code bug, but the tester script is sensitive to it (gotcha added to [[Data Model]]).
2. `/_control/reset` invalidates the api's stored tokens, so the first publish after a reset is `401 → refresh → resend` inside one attempt. probe2 counts `/_stats` rows excluding 401 for the "exactly 3 requests" check.
3. Retry-After as HTTP-date: the fake platform sends `ceil(now) + N` so the gap is never under N; the client waits exactly `date - now`.
4. `failed` entries are retried (same key) on the next publish; `publishing` with no `platform_post_id` (crash mid-call) also retries with the same key.
5. Worth probing: concurrent publishes of one campaign (no row lock; the platform key dedupes, but `attempts` can race); a 2xx with a body missing `id` would 500 (fake platform never does this).
6. The tests run against the baked image; `docker compose run` does not mount source, so rebuild (`make up`) before `make test`/`make lint`.
## Frontend report — Iteration 1
## Tester — Iteration 1 — FAIL
New regression probes: `scripts/probes/stage3_tester.py` (host python3: independent P1/P2/P6, tampering, bad ids, concurrency; resets the fake platform at the end) and `scripts/probes/stage3_bad_2xx.py` (run inside api: `docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py`).

| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Boot | PASS | `make up` → all containers Healthy; `curl :8000/health` 200, `:9000/health` 200 |
| Lint | PASS | `make lint` → `All checks passed!` / `60 files already formatted` |
| Tests + coverage | PASS | `docker compose run --rm api pytest -q --cov=app --cov=fake_platform` → `233 passed`, TOTAL 98% (publishing.py 100%, fake.py 100%, tokens.py 90%) |
| make probe / probe5 (x2) | PASS | 21 PASS, no FAIL / 9 PASS `ALL PASS`, both runs |
| stage2_tester.sh (x2) | PASS | `CHECKS FAILED: 0` `ALL PASS`, 208 PASS lines, both runs (the 500s in the api log come from its own injected render fault) |
| probe1 / probe2 / probe6 (x2 back to back, and again after the tester's tampering) | PASS | exit 0 `ALL PASS` every time; 13 s / 11 s / 2 s; probe2 gaps `[2.02, 2.02]` s and http-date `[2.45, 3.02]`, `[2.92, 2.99]` |
| P1 key committed before the call | PASS | row read 1.5 s into a dropped call: `<sha256(cid:pid:x)>\|publishing\|0\|NULL`, and `/_stats` already holds a request with that key (attempts still 0, so the commit came before the call returned) |
| P1 timeout then retry; publish twice | PASS | 5.4 s, attempts 2, 2 requests with the same key, `exactly 1 post`; second publish: `no new POST /v1/posts`, still 1 post |
| P2 Retry-After 3 s (seconds / http-date) | PASS | statuses `[429,429,201]`; gaps `[3.03, 3.02]` / `[3.22, 4.03]` (all ≥3 s, ≤5 s) |
| P2 Retry-After 120 > MAX 60 | PASS | `took 0.02s`, failed, attempts 1, 1 request, `last_error='Retry-After 120s exceeds MAX_RETRY_AFTER_SECONDS=60'`; next publish retries with the same key → accepted |
| P2 failure_rate 1.0 | PASS | 3 runs: failed, attempts 5, exactly 5×503 each; every gap ≤ its jitter ceiling (0.5/1/2/4 s); mean gaps `[0.25, 0.19, 0.84, 2.64]` (grow). Statistical check; full jitter means one run's gaps need not be monotonic |
| P6 dump + all logs | PASS | `pg_dump` + `docker compose logs` (all 5 services): no token from `/_tokens`, no `bearer`; 2 rows, distinct ciphertexts/nonces `2/2/2` |
| P6 tamper ciphertext / 12-byte nonce / truncated ciphertext | PASS | 200, a fresh token is fetched and the row replaced |
| P6 tamper nonce to wrong length (4 bytes) | **FAIL** | `status 500`, `ValueError: Nonce must be between 8 and 128 bytes` → [[ISSUE-006 short nonce in platform_tokens returns 500]] |
| 2xx without `id` (and bad token body) | **FAIL** | Cannot be triggered via the fake platform (no switch). Through a MockTransport: `201 {}`, `201 non-JSON`, token `200 {}`, token `200 <html>` → all `HTTP 500`; `KeyError 'id'`; entry stuck `publishing\|0` → [[ISSUE-007 2xx without id or bad token body returns 500]] |
| Concurrent publishes, same campaign | **FAIL** (minor) | both 200, 1 post per platform (platform dedupes), but `requests sent 2 ... attempts recorded 1` (lost update, cap per request) → [[ISSUE-008 concurrent publishes double-send and undercount attempts]] |
| Architecture | PASS | `grep publishers.fake\|Fake*Publisher app/services app/api app/worker` → none; services import only `PublishRequest, get_publisher`; one `client.post` per adapter path (+ the token call); no `status='published'` assignment anywhere in `app/`; probe1 shows `{'publishing'}` after 201 |
| Bad input on the endpoint | PASS | 999999999→404; 0, -1, abc, 1.5, 2^63, %00, 1e3 → 422; GET→405; junk body→not 500; already `published` → 200, no request |
| Invalid TOKEN_ENCRYPTION_KEY | PASS | `-e` override with empty / placeholder / 16-byte / non-base64 / truncated keys → `api refuses to start: TOKEN_ENCRYPTION_KEY must be base64 of 32 random bytes; run \`make env\` to create one`, exit 1; through `.env` + `docker compose up` → `api Exited (1)`. `.env` restored (sha1 identical) and the stack rebuilt healthy |
| Secrets | PASS | `git grep -iE "api_key\|secret=" -- ':!*.example'` → only the known hits (PLAN/EVIDENCE/handoff quotes, `gemini_api_key` setting, tests); no hits in the Stage 3 files; `.env` untracked + ignored (`.gitignore:1`); `.env.example` `TOKEN_ENCRYPTION_KEY=` empty; no logger calls in `app/` |

Issues: [[ISSUE-006 short nonce in platform_tokens returns 500]] · [[ISSUE-007 2xx without id or bad token body returns 500]] · [[ISSUE-008 concurrent publishes double-send and undercount attempts]]
Notes: `vault/Stages/Stage 3.md` does not exist yet, so `[[Stage 3]]` links (ADR-002 and these issues) are dangling. Fake platform switches are reset and the stack is healthy with the working `.env`.

<!-- Senior Dev appends "Tasks — Iteration 2" etc. on FAIL -->

## Tasks — Iteration 2
Senior triage of the Tester's FAIL (loop 2 of 3). ISSUE-006, 007 and 008 accepted. Rule behind all three: **a publish must never 500 and never leave an entry stuck in `publishing` with no record of why.**

| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 9 | Backend | ISSUE-006: any failure to decrypt a stored token (`InvalidTag`, `ValueError` from a bad nonce length, wrong types) is treated as "no usable token": fetch a fresh one, overwrite the row, never log the token. | `app/publishers/tokens.py`, `app/crypto.py`, tests | tester's repro (short nonce in `platform_tokens`) → publish 200, fresh token stored; unit test per corruption type |
| 10 | Backend | ISSUE-007: malformed platform replies never raise out of an adapter. Post reply that is 2xx but not JSON or has no string `id` → `retryable("malformed response")` (the same key makes the retry safe; if it never becomes valid the entry ends `failed` with `last_error`). Token reply that is not JSON or lacks `access_token` → `retryable("bad token response")`. Also add a last-resort guard in the service: an unexpected exception while publishing one entry marks that entry `failed` with `last_error` = the exception type (no secrets), commits, and moves on to the next entry; the endpoint still returns 200 with the per-entry result. | `app/publishers/fake.py`, `app/publishers/tokens.py`, `app/services/publishing.py`, tests | `docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py` → no 500, entries end `failed` with a reason after max attempts; unit tests for each malformed shape |
| 11 | Backend | ISSUE-008: count attempts atomically and enforce the cap per entry across concurrent requests: increment with one `UPDATE … SET attempts = attempts + 1 WHERE id = :id AND attempts < :max RETURNING attempts` before each send; if no row comes back, stop. Do not build a claim/lease system (that is Stage 4's worker); the idempotency key already prevents duplicate posts. | `app/services/publishing.py`, `app/repos/`, tests | test: two concurrent publishes on one entry → `attempts` equals the number of requests in `/_stats`, never above `PUBLISH_MAX_ATTEMPTS`; still exactly 1 post |
| 12 | Backend | Close ISSUE-006/007/008 (status closed, resolution, link the fix); update [[Publisher Adapters]], [[Token Crypto]], [[Publishing Service]] notes. | `vault/` | notes updated |

Rebuild (`make up`) before testing. Re-run `make probe1 probe2 probe6`, `python3 scripts/probes/stage3_tester.py`, the bad-2xx script, and the Stage 1/2 regressions. Do not commit.

## Backend report — Iteration 2
**Status:** tasks 9–12 done. Nothing committed.

### Files
- `app/publishers/tokens.py`: decrypt failures (`InvalidTag`, `ValueError`, `TypeError`) mean "fetch a fresh token". New `BadTokenResponse` for a 2xx token reply with no string `access_token`.
- `app/publishers/fake.py`: a 2xx that is not JSON or has no non-empty string `id` → `retryable("malformed response")`. `BadTokenResponse` → `retryable("bad token response")`.
- `app/crypto.py`: docstring only (states the `ValueError` case).
- `app/repos/campaigns.py`: `take_attempt(session, entry_id, max)` runs one `UPDATE … attempts = attempts + 1 WHERE id AND attempts < max RETURNING attempts`.
- `app/services/publishing.py`: `take_attempt` + commit before each send, and the loop stops on `None`. An entry already at the cap → `failed` with no request. Last-resort guard per entry: rollback, `failed`, `last_error` = exception type, commit, continue. Each entry is refreshed afterwards (attempts is written in SQL).
- Tests: `tests/unit/test_publishers.py` (+13 cases: 4 token-row corruptions, 5 malformed 2xx, 4 bad token bodies), `tests/unit/test_publishing.py` (+4: guard, malformed ×5 → failed, exhausted not retried, two threads share the cap).
- Vault: [[Token Crypto]], [[Publisher Adapters]], [[Publishing Service]] updated. ISSUE-006/007/008 closed with resolutions, and `_Issues Index` updated.

### Behaviour change (Tester please note)
1. **`attempts` is now counted and committed *before* the send** (task 11 as specified). `stage3_tester.py`'s check "mid-flight row: … attempts 0" now reads `publishing|1|NULL` and fails. The key is still committed before the call, so the invariant holds. The expected value in that check should be `1`.
2. The attempt cap is now **per entry in total**, not per request. A `failed` entry is retried on the next publish only while `attempts < PUBLISH_MAX_ATTEMPTS`. An exhausted entry stays `failed` and sends nothing.
3. Known race (shortcut comment in the code; Stage 4 removes it): no claim/lease. Request B can commit `publishing` after request A has used the last attempt and set `failed`. B then stops with no attempt, and the entry reads `publishing` until the next publish marks it `failed`. No extra request is sent and no duplicate post is possible.

### How to run
`make up`, then `make probe1 probe2 probe6`, `python3 scripts/probes/stage3_tester.py`, `docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py`.

### Commands and results
- `make up` → all containers Healthy
- `make lint` → `All checks passed!` / `62 files already formatted`
- `make test` → `250 passed, 2 warnings in 24.76s` (same 2 pre-existing warnings)
- `make probe1` → exit 0, 11/11 PASS, `ALL PASS` (includes `key stored + committed before the call returned`, `2 attempts each (timeout, then replay)`)
- `make probe2` → exit 0, `ALL PASS`; gaps `[2.26, 2.11]` s (seconds), `[2.46, 3.04]` s (http-date)
- `make probe6` → exit 0, 8/8 PASS, `ALL PASS`
- `make probe` → exit 0, 21 PASS, 0 FAIL
- `make probe5` → exit 0, `ALL PASS`
- `bash scripts/probes/stage2_tester.sh` → `ALL PASS`
- `python3 scripts/probes/stage3_tester.py` → exit 1, `CHECKS FAILED: 1`, 56 PASS. The one FAIL is note 1 above: `mid-flight row … (got '<key>|publishing|1|NULL', want '<key>|publishing|0|NULL')`. Previously failing checks now pass: `PASS  short nonce: no 500`; concurrent `instagram: requests sent 2, posts 1, attempts recorded 2` → `PASS  … requests sent == attempts recorded` (same for x).
- `docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py` → exit 0, 32.6 s:
  ```
  PASS  201 {} (no id): HTTP 200 entry=('failed', 5, 'malformed response')
  PASS  201 non-JSON body: HTTP 200 entry=('failed', 5, 'malformed response')
  PASS  token 200 without access_token: HTTP 200 entry=('failed', 5, 'bad token response')
  PASS  token 200 non-JSON: HTTP 200 entry=('failed', 5, 'bad token response')
  ```

### Focus for the Tester
- Update the mid-flight `attempts 0` expectation (note 1), then re-run `stage3_tester.py`.
- Concurrent publishes with `failure_rate 1.0` across 2–3 requests should give total requests == attempts == 5.
- The last-resort guard records only the exception type, so check that no token can reach `last_error`.
## Tester — Iteration 2 — FAIL
ISSUE-006/007/008 are fixed and every requested check is green twice. FAIL only because of one new defect, found while stressing concurrency at the attempt cap: [[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]]. The Senior can fix it now or defer it to the Stage 4 claim.
Probe changes (my scripts only): `stage3_tester.py` mid-flight check now expects `publishing|1|NULL` (Senior decision). Added 6 token corruptions, 2 runs of 3 concurrent publishes at `failure_rate 1.0`, and an "exhausted entry stays failed" check. `stage3_bad_2xx.py` has 11 cases: 6 malformed 201s, 4 bad token bodies, and the last-resort guard with a secret in the exception message. It now asserts `failed`/5/reason, not just "no 500". New `stage3_concurrency_stress.py RATE CONC N [PRESET]` repros ISSUE-009.

| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Boot | PASS | `make up` → all Healthy; `/health` api 200, fake 200 |
| P1 mid-flight (updated) | PASS | `PASS  mid-flight row: key=sha256(cid:pid:x), publishing, attempts 1, no post id` + `PASS  mid-flight: the platform already received a request with that key` |
| ISSUE-006 corruptions | PASS | 4-byte, empty and 200-byte nonce; empty, 1-byte and minus-last-byte ciphertext; flipped byte; zeroed 12-byte nonce; 5-byte ciphertext → each `status 200 entry publishing\|1\|None` and `row replaced, 12-byte nonce, new ciphertext`. Afterwards no `/_tokens` value and no `bearer` in `pg_dump` or any container log |
| ISSUE-007 malformed 2xx | PASS | `docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py` → exit 0, 11/11. `201 {}`/non-JSON/`id` int/`id ""`/list/`null` → `('failed', 5, 'malformed response')`; token `{}`/`<html>`/int/list → `('failed', 5, 'bad token response')` |
| ISSUE-007 last-resort guard | PASS | `RuntimeError("Authorization: Bearer probe-secret-tok-9f3a")` on 1st entry → `{'instagram': ('failed', 1, 'RuntimeError'), 'x': ('publishing', 1, None)}` (type only, next entry still published); `last_error ilike '%probe-secret%' or '%bearer%'` → 0 rows; api log grep → 0 |
| ISSUE-008 concurrency | PASS | 2 publishes held in flight: `instagram: requests sent 2, posts 1, attempts recorded 2` (same for x). 3 publishes at `failure_rate 1.0`, 2 runs: `requests 5, row failed\|5` for both platforms, 0 posts. Stress `0.6 4 15`: 0 anomalies; attempts == requests and never > 5 in every stress run |
| Exhausted entry | PASS | after `failed\|5`, two more publishes against a healthy platform → `rows unchanged ['failed\|5\|NULL']*2`, `no request sent by later publishes` (0) |
| Stuck in `publishing`? | PASS (no permanent case) | The documented race reproduces: `0.7 3 20` → 3× `publishing\|5\|NULL`, and `1.0 8 20 preset 4` → 7×. In every case the next publish settles it to `failed\|5`, with no request (393, 417 checked). Accepted entries stay `publishing` with a post id by design until the Stage 5 webhook. I found no path that keeps a no-id entry in `publishing` past the next publish |
| Accepted post marked failed | **FAIL** | `stage3_concurrency_stress.py 0.5 8 25 3` → `anomalies=22`, e.g. `414 instagram failed\|5\|<post id>\|HTTP 503` (1 post on the platform); `0.5 8 25 4` → 11. Two more healthy publishes leave it `failed` with a post id (permanent, because entries with `platform_post_id` are skipped). Also `publishing\|5\|<id>\|HTTP 503` (stale `last_error` on accepted entries) → [[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]] |
| Regression run 1 / run 2 | PASS / PASS | `make lint` `All checks passed!` `63 files already formatted` ×2 · `make test` `250 passed` ×2 · `make probe` `PASS=21 FAIL=0` ×2 · `make probe5` `ALL PASS` ×2 · `stage2_tester.sh` `CHECKS FAILED: 0` `ALL PASS` ×2 · `make probe1` 11 PASS `ALL PASS` ×2 · `make probe2` `ALL PASS`, gaps `[2.27, 2.21]`/`[3.1, 3.05]` then `[2.09, 2.22]`/`[2.9, 3.3]` · `make probe6` `ALL PASS` ×2 · `stage3_tester.py` `PASS=86` `CHECKS FAILED: 0` ×2 · bad_2xx 11/11 |
| Coverage | PASS | `pytest -q --cov=app --cov=fake_platform` → `250 passed`, TOTAL 98%; publishing.py, fake.py, tokens.py, crypto.py 100% |
| Secrets | PASS | `git grep --untracked -iE "api_key\|secret=\|BEGIN (RSA\|PRIVATE)\|access_token=…"` → only known hits (README `GEMINI_API_KEY` mention, `gemini_api_key` setting/header, fake_platform.sh `client_secret=b`, test key); `.env` ignored (`.gitignore:1`); no logger calls in `app/` except the worker's `worker idle` |
| Architecture | PASS | `grep -rnE "publishers\.fake\|Fake[A-Za-z]*Publisher\|from app\.publishers\.(fake\|tokens)" app/services app/api app/worker` → none; the only import is `from app.publishers import PublishRequest, get_publisher` |

Issues: [[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]] (backend, open). ISSUE-006/007/008 confirmed closed.
State: stack healthy, `.env` sha unchanged (`shasum -c` OK), fake platform reset (`failure_rate 0.0`, all switches off). Nothing committed; no app code edited.

## Tasks — Iteration 3 (last loop)
Senior triage: ISSUE-009 accepted and fixed now, not deferred. A post that the platform accepted must never be recorded as `failed`; that is exactly the trust this stage is graded on. This is loop 3 of 3, so keep the change minimal and targeted.

| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 13 | Backend | ISSUE-009: replace the ORM "last commit wins" writes in `_publish_entry` with conditional SQL updates. **Accepted:** `UPDATE … SET platform_post_id = :pid, status = 'publishing', last_error = NULL WHERE id = :id` (acceptance always wins). **Failure:** `UPDATE … SET status = 'failed', last_error = :err WHERE id = :id AND platform_post_id IS NULL` (never overwrites an accepted entry). Before each send, re-read `platform_post_id` (or fold it into `take_attempt`'s WHERE: `AND platform_post_id IS NULL`) so a request stops once another one has been accepted. No locks, no lease (Stage 4). | `app/services/publishing.py`, `app/repos/campaigns.py`, tests | `python3 scripts/probes/stage3_concurrency_stress.py 0.5 8 25 3` → 0 anomalies (no entry with a post id is `failed`, no accepted entry keeps a `last_error`); a unit test reproduces the interleaving (accept then a late failure write) and asserts the entry stays `publishing` with its post id |
| 14 | Backend | Close ISSUE-009; update [[Publishing Service]] note (invariant: "an entry with a `platform_post_id` is never `failed`"). | `vault/` | note updated |

Rebuild, then the full regression: make lint, make test, make probe, make probe5, stage2_tester.sh, make probe1/2/6, stage3_tester.py, stage3_bad_2xx.py, stage3_concurrency_stress.py. Do not commit.

## Backend report — Iteration 3
**Tasks 13–14 done.** ISSUE-009 closed.

**Files changed**
- `app/repos/campaigns.py` — `take_attempt` adds `AND platform_post_id IS NULL`; new `mark_accepted`, `record_error`, `mark_publishing` (all conditional `UPDATE`s).
- `app/services/publishing.py` — `_publish_entry` and the last-resort guard in `publish_campaign` write status, `last_error`, `platform_post_id` only through those functions (no ORM writes of outcome columns). Removed the "documented race" shortcut comment: the race is gone.
- `tests/unit/test_publishing.py` — `test_late_failure_never_overwrites_accepted[0,4]`, `test_late_publishing_write_never_undoes_failed`.
- `vault/Modules/Publishing Service.md` (new invariant: an entry with a `platform_post_id` is never `failed` and has no `last_error`), `vault/Issues/ISSUE-009 …md` (closed + resolution), `vault/Issues/_Issues Index.md`.

**Beyond the literal task 13 text (same pattern, needed for 0 anomalies):** with only the accept/fail writes made conditional, the stress probe still showed `publishing|5|NULL` (4/50 and 2/50). Two more last-write paths caused it: (a) a request that loaded the entry earlier committing `status='publishing'` after a concurrent final failure → now `mark_publishing … WHERE attempts < max`; (b) an earlier attempt's late retryable error writing `publishing` over a concurrent final `failed` → `record_error` adds `AND status <> 'failed'` when writing `publishing`.

**How to run:** `make up`, then `python3 scripts/probes/stage3_concurrency_stress.py 0.5 8 25 3`.

**Commands and results (final image)**
```
make up                                   -> up=0, all containers Healthy
make lint                                 -> All checks passed! / 63 files already formatted
make test                                 -> 253 passed, 2 warnings in 17.15s
make probe                                -> exit=0 PASS=21 FAIL=0
make probe5                               -> exit=0 PASS=9  FAIL=0 | ALL PASS
bash scripts/probes/stage2_tester.sh      -> exit=0 PASS=208 FAIL=0 | ALL PASS
make probe1                               -> exit=0 PASS=11 FAIL=0 | ALL PASS
make probe2                               -> exit=0 PASS=10 FAIL=0 | ALL PASS
make probe6                               -> exit=0 PASS=8  FAIL=0 | ALL PASS
python3 scripts/probes/stage3_tester.py   -> exit=0 PASS=86 FAIL=0 | CHECKS FAILED: 0
docker compose exec -T api python -I - < scripts/probes/stage3_bad_2xx.py -> exit=0 PASS=11 FAIL=0
python3 scripts/probes/stage3_concurrency_stress.py 0.5 8 25 3  (x2) -> rate=0.5 conc=8 n=25 preset=3 anomalies=0 (both)
python3 scripts/probes/stage3_concurrency_stress.py 0.5 8 25 4  (x2) -> rate=0.5 conc=8 n=25 preset=4 anomalies=0 (both)
```
Intermediate run (before the fix for path (b)), for the record: `preset=4` once gave `anomalies=1`: `(921, 'instagram', 'failed|5|NULL|RemoteProtocolError', 0, 0, ['req0!=att5-4'])`, exit 1. That is one attempt counted that the fake platform never logged: the connection dropped before the server handled it (likely a reused keep-alive connection closed under load). The state is correct (attempt counted, no post, `failed`) and it is unrelated to ISSUE-009. It did not recur in the 4 final runs.

**Tester focus**
- Run the stress probe several times, presets 3 and 4, plus a fresh run (`0.7 3 20`): expect `anomalies=0`, including no `publishing-no-id`.
- The `req0!=att5-4` / `RemoteProtocolError` flake above: if it recurs, it is a probe/transport artefact (the platform never saw the request), not a state bug.
- Behaviour change: a late retryable error no longer overwrites `last_error` on an entry a concurrent request already failed; the `failed` request's error is kept.

## Tester — Iteration 3 — PASS
ISSUE-009 is fixed. Every required check is green twice, and the harsher stress runs are clean. I found no new defects.
Probe change (my script only): `stage3_concurrency_stress.py` now checks the Senior's invariant: `logged requests <= attempts - preset`, `attempts <= 5`, at most 1 post per key, an entry with a post id has exactly 1 post, is not `failed` and has no `last_error`, and no `publishing` entry is left without a post id (this is now an anomaly, no longer tolerated). It also runs a settling publish against a healthy platform, then rechecks: there is no stuck `publishing` without a post id, and failed or accepted rows are unchanged with no new request. When an attempt is counted but the platform never logged the request (the RemoteProtocolError case), the script counts it separately as `transport_gaps`, not as an anomaly. Exit 1 on any anomaly.

| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Boot | PASS | `make up` → api, db, fake-platform Healthy; `/health` api 200, fake 200; the container's `/srv/app/repos/campaigns.py` has `take_attempt`/`mark_accepted`/`record_error`/`mark_publishing` |
| ISSUE-009 preset 3 ×2 | PASS | `stage3_concurrency_stress.py 0.5 8 25 3` → `anomalies=0` `outcomes={'accepted': 40, 'failed': 10}` `transport_gaps=0`, exit 0; 2nd → `anomalies=0` `{'accepted': 29, 'failed': 21}` `transport_gaps=0`, exit 0 |
| ISSUE-009 preset 4 ×2 | PASS | `... 0.5 8 25 4` → `anomalies=0` `{'failed': 29, 'accepted': 21}` `transport_gaps=0`, exit 0; 2nd → `anomalies=0` `{'accepted': 23, 'failed': 27}` `transport_gaps=0`, exit 0. Every `last_error` is `HTTP 503`, and only on entries with no post id |
| Harsher stress | PASS | `0.7 3 20` → `anomalies=0` (36 accepted / 4 failed; the old `publishing\|5\|NULL` race is gone) · `0.8 16 15 3` → `anomalies=0` (12/18) · `1.0 12 10 2` → `anomalies=0` (`{'failed': 20}`) · `0.3 16 15` → `anomalies=0` (`{'accepted': 30}`). `transport_gaps=0` in all 8 runs |
| RemoteProtocolError | none seen | 0 transport gaps and 0 `RemoteProtocolError` in `last_error` across 8 runs (510 entries). The backend's one sighting fits a keep-alive race: the shared `httpx.Client` reuses a connection the fake platform's uvicorn has just closed (idle keep-alive timeout), so the server never sees the request. That is a transport artefact under load, not a state bug: the attempt is counted, the request is retryable under the same key, and the invariant (`requests <= attempts`) holds. I could not reproduce it |
| Diff review | PASS | `take_attempt`: `WHERE attempts < max AND platform_post_id IS NULL`. `mark_accepted`: unconditional `SET platform_post_id, status='publishing', last_error=NULL` (acceptance always wins). `record_error`: `WHERE platform_post_id IS NULL` (+ `AND status <> 'failed'` when writing `publishing`). `mark_publishing`: `WHERE attempts < max AND platform_post_id IS NULL`. The last-resort guard goes through `record_error`. `grep -nE "entry\.(status\|last_error\|platform_post_id\|attempts) *=" app/services/publishing.py` → only the read on line 29; the only ORM write left is `idempotency_key`. `grep -iE "with_for_update\|advisory\|lease\|claim\|FOR UPDATE"` → none (no locks or leases). Note: a `failed` row below the cap (fatal, long Retry-After) can still be set back to `publishing` by a later publish. That matches the documented "failed entries are retried on the next publish until the cap", so it is not a late-write undo. A cap-`failed` row cannot be undone (stress settle check plus `test_late_publishing_write_never_undoes_failed`) |
| Regression run 1 | PASS | `make lint` `All checks passed!` `63 files already formatted` · `make test` `253 passed` · `make probe` PASS=21 FAIL=0 · `make probe5` PASS=9 `ALL PASS` · `stage2_tester.sh` PASS=208 `CHECKS FAILED: 0` `ALL PASS` · `make probe1` PASS=11 `ALL PASS` · `make probe2` PASS=10 `ALL PASS`, gaps `[2.12, 2.08]`/`[2.8, 2.97]` · `make probe6` PASS=8 `ALL PASS` · `stage3_tester.py` PASS=86 `CHECKS FAILED: 0` · `stage3_bad_2xx.py` PASS=11 FAIL=0 (guard: `{'instagram': ('failed', 1, 'RuntimeError'), 'x': ('publishing', 1, None)}`). All exit 0 |
| Regression run 2 | PASS | same counts: lint clean · `253 passed` · 21 · 9 · 208 · 11 · 10 (gaps `[2.04, 2.04]`/`[2.49, 3.05]`) · 8 · 86 · 11; all exit 0 |
| Coverage | PASS | `pytest -q --cov=app --cov=fake_platform` → `253 passed`, TOTAL 98%; `publishing.py` 100%, `repos/campaigns.py` 100% |
| Probe lint | PASS | ruff (project config, api image) on `scripts/probes/` → `All checks passed!` `6 files already formatted` |
| Secrets | PASS | `git grep --untracked -iE "api_key\|secret=\|BEGIN (RSA\|PRIVATE)\|access_token=\|bearer [a-z0-9]{12,}"` → only known hits (`.env.example` placeholders, README `GEMINI_API_KEY` mention, `gemini_api_key` setting/header, fake_platform.sh `client_secret=b`, test key); `.env` ignored (`.gitignore:1`); the only logging in `app/` is the worker's `worker idle` |
| Architecture | PASS | `grep -rnE "publishers\.fake\|Fake[A-Za-z]*Publisher\|from app\.publishers\.(fake\|tokens)" app/services app/api app/worker` → none; `publishing.py` imports only `from app.publishers import PublishRequest, get_publisher` |

Issues: none new. [[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]] confirmed closed.
State: stack healthy (api 200, fake 200), `.env` sha `f364e21f…` unchanged, fake platform reset (`failure_rate 0.0`, all switches off, `/_posts` `[]`). Nothing committed; no app code edited.
