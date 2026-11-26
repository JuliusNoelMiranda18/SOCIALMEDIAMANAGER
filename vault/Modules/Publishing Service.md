# Publishing Service

**Purpose:** Publishes every entry of a campaign through `SocialPublisher` and owns the retry policy (idempotency key, Retry-After, backoff, max attempts), per [[ADR-002 Publish flow]].
**Files:** `app/services/publishing.py` (called by [[Worker]]'s `publish_campaign` job handler)
**Last changed:** Stage 5 iteration 2, 2026-11-26 (ISSUE-010: advisory lock in `mark_accepted`)

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `publish_campaign` | `(session, campaign_id, *, sleep=time.sleep) -> Campaign` | skips entries already `published` or with `platform_post_id`; publishes the rest; `NotFound` → 404. Last-resort guard: an unexpected exception on one entry → rollback, entry `failed` with `last_error` = exception type (via `record_error`, so never over an accepted entry), commit, next entry |
| `_publish_entry` | `(session, campaign, entry, sleep)` | key = `sha256("<campaign_id>:<post_id>:<platform>")`, `mark_publishing`, **commit**, then the retry loop |
| `mark_publishing` (`app/repos/campaigns.py`) | `(session, entry_id, max)` | `UPDATE … SET status = 'publishing' WHERE id = :id AND attempts < :max AND platform_post_id IS NULL AND status <> 'published'` — a late request cannot undo a concurrent `failed` |
| `mark_queued` (`app/repos/campaigns.py`) | `(session, campaign_id)` | `draft → queued` for the campaign's entries; called by `services.jobs.schedule_campaign` in the job-insert transaction |
| `take_attempt` (`app/repos/campaigns.py`) | `(session, entry_id, max) -> int \| None` | `UPDATE … SET attempts = attempts + 1 WHERE id = :id AND attempts < :max AND platform_post_id IS NULL RETURNING attempts`; `None` = cap reached or accepted by a concurrent publish |
| `mark_accepted` (`app/repos/campaigns.py`) | `(session, entry_id, platform_post_id)` | `UPDATE … SET platform_post_id = :pid, status = CASE WHEN EXISTS(stored 'delivered' event for :pid) THEN 'published' WHEN EXISTS('failed' event) THEN 'failed' ELSE 'publishing' END, last_error = (failure text or NULL) WHERE id = :id AND status <> 'published'` — acceptance wins over our own errors; an early callback decides the final status |
| `record_error` (`app/repos/campaigns.py`) | `(session, entry_id, error, status)` | `UPDATE … SET status = :status, last_error = :err WHERE id = :id AND platform_post_id IS NULL AND status <> 'published'` (+ `AND status <> 'failed'` when writing `publishing`) — never overwrites an accepted entry, and a late retryable error never revives a concurrently failed one |
| `backoff_seconds` | `(attempt) -> float` | full jitter: `uniform(0, min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2^(attempt-1)))` |

## Retry loop
- Before each `publish()` call: `take_attempt` + commit (the count is durable before the send). No row back → stop. The cap is per entry across all publishes and concurrent requests ([[ISSUE-008 concurrent publishes double-send and undercount attempts]]).
- An entry already at the cap is marked `failed` (keeps `last_error`) without a request.
- All outcomes are conditional SQL writes (`mark_accepted` / `record_error`), not ORM writes, so concurrent requests cannot "last commit wins" each other ([[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]]).
- accepted → store `platform_post_id`, clear `last_error`, `publishing` until the verified [[Webhook]] marks it `published` (or `published` at once if the callback already arrived).
- rate_limited → wait `max(Retry-After, backoff)`; Retry-After > `MAX_RETRY_AFTER_SECONDS` (60) → `failed` at once.
- retryable → wait backoff. fatal or attempts exhausted → `failed`.
- `image_url` sent = `PUBLIC_BASE_URL` + `/media/<file>`.

## Connections
- Depends on: [[Publisher Adapters]] (protocol + factory only), [[Data Model]], [[Api Layer]] (`get_campaign`, `NotFound`)
- Used by: [[Worker]] (`HANDLERS['publish_campaign']`; `POST /campaigns/{id}/publish` now only enqueues), `backoff_seconds` also sets the job retry delay · map: [[System Map]] · contract: [[API]]

## State machine (Stage 5)
`draft → queued → publishing → published | failed`
- `queued`: a publish job was enqueued (`mark_queued`, only from `draft`).
- `publishing`: the worker started (key stored) or the platform accepted (post id stored).
- `published`: only from a verified `delivered` callback ([[Webhook]] `apply_delivery`, or `mark_accepted` seeing a stored event). **Final**: every write in `app/repos/campaigns.py` excludes it.
- `failed`: fatal / exhausted / long Retry-After, or a verified `failed` callback. The **one allowed exit** from `failed` is an explicit publish (Stage 3 retry: `mark_publishing` under the attempt cap).
- Early-callback race: the callback can beat the 201. The webhook stores it (`unmatched`); `mark_accepted` then reads it. If both run at once, a per-post-id `pg_advisory_xact_lock` taken first in both the webhook's transaction and `mark_accepted`'s serializes them, so the second sees the first's commit ([[ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing|ISSUE-010]]; `tests/acceptance/test_stage5_race.py`). The lock is held until the caller's commit.

## Invariants
- Publish never runs without a committed idempotency key; the same key is reused on every retry and every later publish.
- Publishing twice sends nothing for accepted entries.
- `failed` entries are retried (same key) on the next publish, until `attempts` reaches `PUBLISH_MAX_ATTEMPTS` in total.
- An entry with a `platform_post_id` is never `failed` and has no `last_error`, whatever the interleaving.
- A publish never 500s for one bad entry, and never leaves an entry in `publishing` without a post id once the cap is used.

## Tests
- `tests/unit/test_publishing.py` — endpoint is 202 + `run_once` (Stage 4); key visible from a second session inside the transport; Retry-After honoured; backoff 0.5→30 s capped; exhausted → failed; long Retry-After → failed without waiting; fatal; publish twice; token absent from logs; endpoint 200/404/422; services import no adapter; unexpected exception → that entry failed, next entry published; malformed 2xx ×5 → failed `malformed response`; exhausted entry not retried; two concurrent publishes → attempts == requests == 5; `test_late_publishing_write_never_undoes_failed`; `test_late_failure_never_overwrites_accepted[0,4]` — a concurrent accept lands while our request gets 503 (mid-retry and final attempt) → entry stays `publishing` with the post id, no `last_error`, no further send
- `tests/unit/test_webhooks.py` — race fix, `published` guards, `queued` (see [[Webhook]])
- `scripts/probes/probe1_idempotency.sh` (`make probe1`; accepts `publishing` or `published` right after publish since Stage 5), `probe2_rate_limit.sh` (`make probe2`)

## Gotchas
- `attempts`, status outcomes and `platform_post_id` are written in SQL, not through the ORM (`expire_on_commit=False`), so `publish_campaign` refreshes each entry after publishing it.
- Stage 4: the API no longer calls this; one active job per campaign (DB index) plus the job lease stop parallel sends. The conditional writes still guard a reclaimed job overlapping a stale worker.
