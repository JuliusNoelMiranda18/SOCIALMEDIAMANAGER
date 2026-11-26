# ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed

**Status:** closed (Stage 3 iteration 3)
**Stage / iteration:** 3 / 2
**Owner:** backend
**Found by:** tester · [[Stage 3]] · [[Publishing Service]] · [[_Issues Index]]

## Reproduce
```
make up
# entries already failed with 3 attempts (a prior publish), failure_rate 0.5, 8 concurrent publishes, 25 campaigns
python3 scripts/probes/stage3_concurrency_stress.py 0.5 8 25 3 ; echo exit=$?
# then, with the platform healthy, publish an affected campaign twice more
curl -XPOST localhost:8000/campaigns/<cid>/publish   # x2
```

## Expected
Whatever the interleaving, an entry the platform accepted (has `platform_post_id`) is never `failed`, and an accepted entry has no `last_error`. ISSUE-008's per-entry cap holds (it does), and the row reflects the outcome that actually happened.

## Actual
`rate=0.5 conc=8 n=25 preset=3 anomalies=22` and `preset=4 anomalies=11`, for example:
```
(414, 'instagram', 'failed|5|2194afed-…|HTTP 503', 2 requests, 1 post, ['failed-with-id', 'id-with-error'])
(420, 'instagram', 'failed|5|3d276061-…|NULL',     2 requests, 1 post, ['failed-with-id'])
(430, 'x',         'publishing|5|b1894ebc-…|HTTP 503', 2 requests, 1 post, ['id-with-error'])
```
After two more publishes against a healthy platform the rows are unchanged (`414|instagram|failed|5|has_id=t|HTTP 503`, `420|instagram|failed|5|has_id=t|`): `publish_campaign` skips any entry with a `platform_post_id`, so the entry stays `failed` for good while its post is live on the platform (exactly 1 post, no duplicate). The API and dashboard would report a published post as failed.
Attempts still equal requests and never exceed 5; no 500; no duplicate post. With fresh entries (`0.7 3 20`, no preset) only the documented `publishing|5|NULL` race appeared (3/20), and the next publish settles it to `failed` as the backend reported.

## Suspected location
`app/services/publishing.py` `_publish_entry`: each concurrent request writes `status`, `last_error` and `platform_post_id` from its own ORM copy, so the last commit wins. Request A gets 201 and sets `platform_post_id`, `last_error=None`; request B gets 503 on the final attempt (`attempt == max_attempts`) and sets `status='failed'`, `last_error='HTTP 503'`. Both column sets land, giving `failed` + post id. A fix that fits "no claim/lease before Stage 4": make the final writes conditional in SQL, e.g. `UPDATE … SET status='failed', last_error=:e WHERE id=:id AND platform_post_id IS NULL`, and on accept `SET platform_post_id=:pid, last_error=NULL, status='publishing'` unconditionally. Or defer to Stage 4's worker claim and record that decision. See [[Publishing Service]].

## Resolution
Every outcome write in `_publish_entry` is now a conditional SQL update in `app/repos/campaigns.py` instead of an ORM "last commit wins" write:
- `mark_accepted`: `SET platform_post_id, status='publishing', last_error=NULL WHERE id` (acceptance always wins).
- `record_error`: `SET status, last_error WHERE id AND platform_post_id IS NULL`, plus `AND status <> 'failed'` when writing `publishing` (a late retryable error cannot revive a concurrently failed entry).
- `mark_publishing`: `SET status='publishing' WHERE id AND attempts < max AND platform_post_id IS NULL` (a late request cannot undo a concurrent `failed`).
- `take_attempt` adds `AND platform_post_id IS NULL`, so a request stops once another one is accepted.
The last two also close the old `publishing|5|NULL` race. No locks or lease.
Proof: `tests/unit/test_publishing.py::test_late_failure_never_overwrites_accepted[0,4]` (accept lands during our 503, mid-retry and final attempt → `publishing` + post id, no `last_error`, no further send), `test_late_publishing_write_never_undoes_failed`; `stage3_concurrency_stress.py 0.5 8 25 3` ×2 and `… 4` ×2 → `anomalies=0`.
