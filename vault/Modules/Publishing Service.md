# Publishing Service

**Purpose:** Publishes every entry of a campaign through `SocialPublisher` and owns the retry policy (idempotency key, Retry-After, backoff, max attempts), per [[ADR-002 Publish flow]].
**Files:** `app/services/publishing.py`, `POST /campaigns/{id}/publish` in `app/api/routes.py`
**Last changed:** Stage 3 iteration 3, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `publish_campaign` | `(session, campaign_id, *, sleep=time.sleep) -> Campaign` | skips entries already `published` or with `platform_post_id`; publishes the rest; `NotFound` → 404. Last-resort guard: an unexpected exception on one entry → rollback, entry `failed` with `last_error` = exception type (via `record_error`, so never over an accepted entry), commit, next entry |
| `_publish_entry` | `(session, campaign, entry, sleep)` | key = `sha256("<campaign_id>:<post_id>:<platform>")`, `mark_publishing`, **commit**, then the retry loop |
| `mark_publishing` (`app/repos/campaigns.py`) | `(session, entry_id, max)` | `UPDATE … SET status = 'publishing' WHERE id = :id AND attempts < :max AND platform_post_id IS NULL` — a late request cannot undo a concurrent `failed` |
| `take_attempt` (`app/repos/campaigns.py`) | `(session, entry_id, max) -> int \| None` | `UPDATE … SET attempts = attempts + 1 WHERE id = :id AND attempts < :max AND platform_post_id IS NULL RETURNING attempts`; `None` = cap reached or accepted by a concurrent publish |
| `mark_accepted` (`app/repos/campaigns.py`) | `(session, entry_id, platform_post_id)` | `UPDATE … SET platform_post_id = :pid, status = 'publishing', last_error = NULL WHERE id = :id` — acceptance always wins |
| `record_error` (`app/repos/campaigns.py`) | `(session, entry_id, error, status)` | `UPDATE … SET status = :status, last_error = :err WHERE id = :id AND platform_post_id IS NULL` (+ `AND status <> 'failed'` when writing `publishing`) — never overwrites an accepted entry, and a late retryable error never revives a concurrently failed one |
| `backoff_seconds` | `(attempt) -> float` | full jitter: `uniform(0, min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2^(attempt-1)))` |

## Retry loop
- Before each `publish()` call: `take_attempt` + commit (the count is durable before the send). No row back → stop. The cap is per entry across all publishes and concurrent requests ([[ISSUE-008 concurrent publishes double-send and undercount attempts]]).
- An entry already at the cap is marked `failed` (keeps `last_error`) without a request.
- All outcomes are conditional SQL writes (`mark_accepted` / `record_error`), not ORM writes, so concurrent requests cannot "last commit wins" each other ([[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]]).
- accepted → store `platform_post_id`, clear `last_error`, keep `publishing` (Stage 5 webhook marks `published`).
- rate_limited → wait `max(Retry-After, backoff)`; Retry-After > `MAX_RETRY_AFTER_SECONDS` (60) → `failed` at once.
- retryable → wait backoff. fatal or attempts exhausted → `failed`.
- `image_url` sent = `PUBLIC_BASE_URL` + `/media/<file>`.

## Connections
- Depends on: [[Publisher Adapters]] (protocol + factory only), [[Data Model]], [[Api Layer]] (`get_campaign`, `NotFound`)
- Used by: [[Api Layer]] (`POST /campaigns/{id}/publish`), Stage 4 worker · map: [[System Map]] · contract: [[API]]

## Invariants
- Publish never runs without a committed idempotency key; the same key is reused on every retry and every later publish.
- Publishing twice sends nothing for accepted entries.
- `failed` entries are retried (same key) on the next publish, until `attempts` reaches `PUBLISH_MAX_ATTEMPTS` in total.
- An entry with a `platform_post_id` is never `failed` and has no `last_error`, whatever the interleaving.
- A publish never 500s for one bad entry, and never leaves an entry in `publishing` without a post id once the cap is used.

## Tests
- `tests/unit/test_publishing.py` — key visible from a second session inside the transport; Retry-After honoured; backoff 0.5→30 s capped; exhausted → failed; long Retry-After → failed without waiting; fatal; publish twice; token absent from logs; endpoint 200/404/422; services import no adapter; unexpected exception → that entry failed, next entry published; malformed 2xx ×5 → failed `malformed response`; exhausted entry not retried; two concurrent publishes → attempts == requests == 5; `test_late_publishing_write_never_undoes_failed`; `test_late_failure_never_overwrites_accepted[0,4]` — a concurrent accept lands while our request gets 503 (mid-retry and final attempt) → entry stays `publishing` with the post id, no `last_error`, no further send
- `scripts/probes/probe1_idempotency.sh` (`make probe1`), `probe2_rate_limit.sh` (`make probe2`)

## Gotchas
- shortcut: runs synchronously in the request, so a campaign with long waits holds the HTTP call; Stage 4 moves it into the worker.
- `attempts`, status outcomes and `platform_post_id` are written in SQL, not through the ORM (`expire_on_commit=False`), so `publish_campaign` refreshes each entry after publishing it.
- shortcut: no claim/lease. Concurrent publishes of one entry share the attempt cap and the key dedupes posts, but both may be in flight at once; correctness comes from the conditional writes alone. Stage 4's worker claim stops the parallel sends.
