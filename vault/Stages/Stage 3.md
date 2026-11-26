# Stage 3 — Adapters, idempotent publish, rate limits, encrypted tokens

**Status:** AWAITING_APPROVAL · **Loops used:** 3/3 · **Date:** 2026-11-26

## Built
- `SocialPublisher` protocol + `FakeInstagramPublisher` / `FakeXPublisher` (one HTTP attempt each) and a factory; services depend on the protocol only. See [[Publisher Adapters]], [[ADR-002 Publish flow]].
- Publish service with the retry policy: idempotency key per entry committed **before** the first call, `Retry-After` (seconds and HTTP-date), exponential backoff with full jitter, max 5 attempts per entry, all status writes conditional so an accepted post is never marked failed. See [[Publishing Service]].
- `POST /campaigns/{id}/publish` (synchronous until Stage 4). A 201 from the platform leaves the entry `publishing`; only Stage 5's verified webhook marks it `published`.
- Platform tokens AES-GCM encrypted at rest (random nonce, platform as AAD), refreshed on 401 or corruption, never logged. `make env` creates `.env` with a random key; the api refuses to start on a bad key. See [[Token Crypto]].
- Migration `0002_publish` (idempotency_key, attempts, last_error). See [[Data Model]].
- Fake platform: `rate_limit.count`, `rate_limit.format`, `/_stats`, `/_tokens`. See [[Fake Platform]].
- Probes `make probe1`, `probe2`, `probe6`; tester scripts `stage3_tester.py`, `stage3_bad_2xx.py`, `stage3_concurrency_stress.py`.

## Tester evidence
| Check | Result | Evidence |
|---|---|---|
| Probe 1: publish twice + retry after timeout → 1 post per platform | PASS | key read from DB 1.5 s into an in-flight call |
| Probe 2: Retry-After honoured, no hammering | PASS | `[429,429,201]`, gaps ≥2 s (seconds and HTTP-date); 120 s Retry-After fails at once; 5×503 then stop, growing gaps |
| Probe 6: no plaintext token | PASS | `pg_dump` + logs of all 5 containers, every token from `/_tokens` absent |
| Corrupt token row (8 kinds) | PASS | fresh token fetched, 200 |
| Malformed platform replies (11 cases) | PASS | no 500; entry `failed` with a reason; a planted secret never stored |
| Concurrency stress (8 runs, 510 entries, up to 16 concurrent) | PASS | `anomalies=0`; logged requests ≤ attempts ≤ 5; ≤1 post per key |
| Architecture | PASS | no adapter import in services/api; nothing sets `published` |
| Regression ×2 | PASS | lint clean, 253 passed (98%, publishing 100%), probes 0/1/2/5/6 + stage 2/3 scripts green |

Full output: [[Current Handoff]] (Tester, Iterations 1–3).

## Your manual test (do this before /approve 3)
1. `cd /Users/jouleused/Desktop/SOCIALMEDIAMANAGER && make up`
2. Create a campaign: `make seed`, then in http://localhost:8000/docs run `POST /campaigns` with `{"post_id": <id>, "platforms": ["instagram","x"]}` and note the campaign `id`.
3. Turn on 429 mode for the next two posts: `curl -X POST localhost:9000/_control -H 'content-type: application/json' -d '{"rate_limit":{"enabled":true,"retry_after_seconds":3,"count":2}}'`
4. In another terminal tab watch the api: `docker compose logs -f api`
5. Publish: in Swagger run `POST /campaigns/{id}/publish`. It takes a few seconds (it waits out the 429s). Both entries should come back `publishing` with a `platform_post_id`.
6. Check there was no hammering: `curl -s localhost:9000/_stats` shows 429, 429, then 201, about 3 s apart.
7. Publish the same campaign again: nothing new is sent, and `curl -s localhost:9000/_posts` still has exactly one post per platform.
8. Optional: `make probe1 probe2 probe6`.
9. Reset: `curl -X POST localhost:9000/_control/reset`

## Known limitations
- Publishing is synchronous: a request can block for the full retry schedule (up to `MAX_RETRY_AFTER_SECONDS` per wait). Stage 4 moves it into the worker.
- The attempt cap (5) is per entry for its lifetime: an exhausted entry stays `failed`; there is no "retry later" yet (Stage 4).
- No row claim/lease: concurrent publishes are safe (conditional writes, idempotency key) but can send a duplicate request that the platform replays. Stage 4's `SKIP LOCKED` claim removes it.
- Status stops at `publishing` until Stage 5's verified webhook.
- Media files are not removed when the DB is reset (`./media` can collide with new campaign ids after `alembic downgrade base`).

## Issues closed / still open
- Closed: [[ISSUE-006 short nonce in platform_tokens returns 500]], [[ISSUE-007 2xx without id or bad token body returns 500]], [[ISSUE-008 concurrent publishes double-send and undercount attempts]], [[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]]. Open: none.

## Dead ends logged
None. (ISSUE-009's first fix was extended, not abandoned: two more late writes needed the same conditional pattern.)

## Links
[[00 Home]] · [[_Stages Index]] · [[System Map]] · [[ADR-002 Publish flow]] · previous: [[Stage 2]]

## Next stage preview
Stage 4: durable scheduler + worker (`run_at`, `SKIP LOCKED` claim, lease expiry, `POST /campaigns/{id}/schedule`, test clock); probe 3 kills the worker mid-batch and expects zero duplicates.

## Approval
_Approved by user on <date>_
