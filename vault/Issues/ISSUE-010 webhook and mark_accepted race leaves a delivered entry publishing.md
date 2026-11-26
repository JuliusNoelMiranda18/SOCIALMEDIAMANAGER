# ISSUE-010 webhook and mark_accepted race leaves a delivered entry publishing

**Status:** verified (Stage 5 iteration 2, tester: race test 2 passed)
**Stage / iteration:** 5 / 1
**Owner:** backend
**Found by:** tester · [[Stage 5]] · [[Webhook]] · [[Publishing Service]] · [[_Issues Index]]

## Reproduce
```
make up   # rebuilds the image so tests/acceptance is inside it
docker compose run --rm api pytest -q tests/acceptance/test_stage5_race.py
```
Two real sessions, interleaved by hand; the second writer runs in a thread with a 1 s join, so a
lock-based fix (second writer waits for the first commit) passes and the current code fails.
- Order A: webhook tx `store` + `apply_delivery` (0 rows, the post id is not visible yet), not committed → worker `mark_accepted` + commit (its `EXISTS` cannot see the uncommitted event → `publishing`) → webhook commits.
- Order B: worker `mark_accepted` written, not committed → webhook `store` + `apply_delivery` (scans the old row version, `platform_post_id IS NULL`, so it matches nothing and does **not** block) + commit → worker commits.

## Expected
A verified `delivered` event is stored for the post id, so the entry ends `published` in both orders.

## Actual
```
E       AssertionError: assert 'publishing' == 'published'
tests/acceptance/test_stage5_race.py:68: AssertionError
E       AssertionError: assert 'publishing' == 'published'
tests/acceptance/test_stage5_race.py:79: AssertionError
2 failed, 1 warning in 0.92s
```
Permanent: the fake platform never retries the callback and nothing else re-reads `webhook_events`,
so the entry stays `publishing` forever with a verified `delivered` event in the DB. Under READ
COMMITTED each side's statement snapshot misses the other's uncommitted write. The window is real
in production: the callback is sent as a background task right after the 201, i.e. while the worker
is between receiving the 201 and committing `mark_accepted`.

## Suspected location
`app/repos/campaigns.py::mark_accepted` and `apply_delivery`, `app/services/webhooks.py::handle` — [[Webhook]], [[Publishing Service]]

Fix direction: both sides take `SELECT pg_advisory_xact_lock(hashtext(:platform_post_id))` before
their write (the webhook before `store`, the worker before `mark_accepted`'s UPDATE), so the second
transaction waits for the first to commit and then its statement sees it. Order B then needs the
worker's lock held until its commit (xact lock does that). The two tests above are the acceptance check.

## Resolution
`app/repos/webhooks.py::store` and `app/repos/campaigns.py::mark_accepted` now run `SELECT pg_advisory_xact_lock(hashtext(:platform_post_id))` as their first statement, so the two writers for one post id serialize and the second sees the first's commit. `tests/acceptance/test_stage5_race.py` (both orders) now passes: `2 passed`.
