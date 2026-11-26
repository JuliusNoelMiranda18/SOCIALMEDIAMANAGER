# Issues Index

Tester creates `ISSUE-XXX <title>.md` from [[Issue]] (template). Number sequentially.

| ID | Title | Owner | Status | Stage |
|---|---|---|---|---|
| [[ISSUE-001 pytest-cov missing from dev deps]] | pytest-cov missing from dev deps | backend | closed | 0 |
| [[ISSUE-002 ruff format fails on test_fake_platform]] | ruff format --check fails | backend | closed | 1 |
| [[ISSUE-003 failure_rate NaN or Infinity returns 500]] | NaN/Infinity failure_rate -> 500 | backend | closed | 1 |
| [[ISSUE-004 X template caption breaks length and hashtag rules]] | X caption >280 chars / 3 hashtags from user input | backend | closed | 2 |
| [[ISSUE-005 brand strip bottom row is 1px inside the margin]] | brand strip 1px into safe margin (minor) | backend | closed | 2 |
| [[ISSUE-006 short nonce in platform_tokens returns 500]] | wrong-length nonce -> ValueError -> 500 | backend | closed | 3 |
| [[ISSUE-007 2xx without id or bad token body returns 500]] | 2xx w/o `id` / token body w/o `access_token` -> 500, entry stuck | backend | closed | 3 |
| [[ISSUE-008 concurrent publishes double-send and undercount attempts]] | concurrent publish: 2 requests, attempts=1 (no row claim) | backend | closed | 3 |
| [[ISSUE-009 concurrent publish at the cap leaves an accepted post marked failed]] | concurrent publish at the cap: accepted post ends `failed` (+ stale `last_error`), permanent | backend | closed | 3 |
