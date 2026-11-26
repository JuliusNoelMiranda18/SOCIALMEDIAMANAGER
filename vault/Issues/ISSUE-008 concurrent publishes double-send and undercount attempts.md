# ISSUE-008 concurrent publishes double-send and undercount attempts

**Status:** closed (Stage 3 iteration 2)
**Stage / iteration:** 3 / 1
**Owner:** backend
**Found by:** tester · [[Stage 3]] · [[Publishing Service]] · [[_Issues Index]]

## Reproduce
```
python3 scripts/probes/stage3_tester.py   # section "two concurrent publishes of the same campaign"
# drop_response delay 3 s (< PUBLISH_TIMEOUT 5 s) holds the first call in flight;
# a second POST /campaigns/<id>/publish arrives 0.2 s later
```

## Expected
One publish of the campaign is in flight at a time. The platform receives one request per recorded attempt, and the `PUBLISH_MAX_ATTEMPTS` cap holds per entry.

## Actual
```
PASS  both responses 200
      instagram: requests sent 2, posts 1, attempts recorded 1
FAIL  instagram: requests sent == attempts recorded (got '2', want '1')
      x: requests sent 2, posts 1, attempts recorded 1
FAIL  x: requests sent == attempts recorded (got '2', want '1')
```
The result was the same on two runs. There are no duplicate posts, because the platform dedupes by key. But both requests treat `publishing` with no `platform_post_id` as "retry me", so both send. `entry.attempts += 1` on stale ORM state is a lost update, and the attempt cap applies per request rather than per entry: N concurrent publishes can send up to N×5 requests. There is no 500.

## Suspected location
`app/services/publishing.py` `publish_campaign`/`_publish_entry`: nothing claims the entry. Options: a conditional UPDATE that claims the row (`... where id=? and <not in flight>` returning rowcount), `SELECT ... FOR UPDATE SKIP LOCKED`, and `attempts = attempts + 1` done in SQL. This may be deferred to Stage 4 (worker job claiming), but it needs a decision. See [[Publishing Service]].

## Resolution
Each attempt is counted atomically before the send with `UPDATE … SET attempts = attempts + 1 WHERE id AND attempts < max RETURNING attempts` (`app/repos/campaigns.py::take_attempt`), committed, and the loop stops when no row comes back. The cap now holds per entry across publishes and concurrent requests. There is no claim/lease (Stage 4) ([[Publishing Service]]). Proof: `test_concurrent_publishes_share_the_attempt_cap` (attempts == requests == 5), `test_exhausted_entry_is_not_retried`; `stage3_tester.py` → `requests sent 2 … attempts recorded 2`, PASS.
