# Stage 5 — Signed webhook + status tracking

**Status:** AWAITING_APPROVAL · **Loops used:** 2/3 · **Date:** 2026-11-26

## Built
- **`POST /webhook/social-delivery`** ([[Webhook]], `app/services/webhooks.py`): checks the **raw** body before parsing it.
  - Both headers must be present and the timestamp must be an int.
  - The timestamp must be within ±`WEBHOOK_TOLERANCE_SECONDS` (300).
  - `hmac.compare_digest` checks HMAC-SHA256 over `"<ts>.<raw body>"`.
  - Only then is the JSON parsed, with a strict model, and the body timestamp must match the header.
  - Any rejection → 400 with a short reason, no DB write, and a log line holding only the reason.
- **Dedupe** ([[Data Model]], migration `0004_webhooks`): only verified events are stored (`ON CONFLICT (event_id) DO NOTHING`). A repeat delivery → `{"result":"duplicate"}`, with nothing applied twice. A forged request can never use up a real `event_id`.
- **State machine** ([[Publishing Service]]): `draft → queued → publishing → published | failed`.
  - Enqueueing a job sets `queued`.
  - Only a verified `delivered` event sets `published`. A `failed` event sets `failed`.
  - `published` is final: every write excludes it.
  - `failed` can be left only by an explicit publish (Stage 3 retry).
- **Early-callback race** ([[ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing]]):
  - The callback can arrive before the worker stores the post id. `mark_accepted` reads any stored verified event, and both writers take `pg_advisory_xact_lock(hashtext(post_id))` first. So the entry ends `published` whichever transaction goes first.
  - The race is covered by `tests/acceptance/test_stage5_race.py`, which runs both orderings.
- **Real webhook secret:** `make env` now fills `WEBHOOK_SECRET` (`token_hex(32)`) when it is empty or a placeholder. It never replaces a real one and never prints it.
- **Probe 4** (`make probe4`): forged → stays `publishing`; valid → `published`; duplicate → processed once; stale → 400; tampered → 400; `failed` after `published` → unchanged.

## Tester evidence
| Check | Result | Evidence |
|---|---|---|
| Probe 4 (exit criterion) | PASS | `make probe4` → 15 PASS, `ALL PASS` (iter 1 and 2) |
| Race, both orderings | FAIL → PASS | iter 1: `2 failed` (`'publishing' == 'published'`); iter 2: `2 passed` |
| Unit tests | PASS | `make test` → `300 passed` |
| Lint | PASS | `All checks passed!`, `73 files already formatted` |
| Regression | PASS | iter 1: `make probe probe5 probe1 probe2 probe6 probe3` all PASS; iter 2: `probe1 probe3` ALL PASS |
| No 500 on bad webhook input | PASS | `scripts/probes/probe4_bad_inputs.sh`, 15 cases → all 400, 0 rows stored (54 → 54) |
| Migration round trip | PASS | `alembic downgrade 0003 && upgrade head` → `0004 (head)` |
| Secret hygiene | PASS | no secret or signature in logs or git; `make env` twice → "wrote", then "already set" |

## Your manual test (optional; steps from PLAN.md)
1. `make env && make up` (the containers must pick up the generated `WEBHOOK_SECRET`).
2. Forged mode on: `curl -X POST localhost:9000/_control -H 'Content-Type: application/json' -d '{"forged_signature":true}'`.
3. Create a campaign and `POST /campaigns/<id>/publish`. After a few seconds, `GET /campaigns/<id>` → entries stay `publishing`; `docker compose logs api | grep "webhook rejected"` shows `bad signature`.
4. Forged off (`{"forged_signature":false}`), publish a **new** campaign → its entries become `published`.

## Known limitations
- The fake platform never retries callbacks, so a callback lost in transit (api down) leaves the entry `publishing`. There is no reconciliation poll yet.
- A platform `failed` callback leaves the entry `failed` **with** a post id. `publish_campaign` skips entries that have a post id, so publishing again does not retry it.
- The api still starts with the placeholder `WEBHOOK_SECRET` if `make env` was never run (no startup refusal).
- An oversized webhook body gets 400 rather than 413.
- Stage 4 limitations still apply (uncapped crash-loop reclaims, no fencing token).

## Issues closed / still open
- Closed: [[ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing]] (verified). Open: none.

## Dead ends logged
- [[DE-001 set literals in probe jget expressions]]: `{a,b}` in a probe's Python expression is brace-expanded by bash and gave a false PASS. Use tuples or lists.

## Links
[[00 Home]] · [[_Stages Index]] · [[System Map]] · [[Webhook]] · [[Publishing Service]] · previous: [[Stage 4]]

## Next stage preview
Stage 6: campaign dashboard (frontend, `web/`). It will list campaigns with per-platform status, schedule and publish them, and show job and webhook state. This is the first stage that uses frontend-dev.

## Approval
_Approved by user on <date>_
