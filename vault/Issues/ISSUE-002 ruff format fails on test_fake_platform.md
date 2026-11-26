# ISSUE-002 ruff format fails on test_fake_platform

**Status:** closed (stage 1 iteration 2)
**Stage / iteration:** 1 / 1
**Owner:** backend
**Found by:** tester · [[Stage 1]] · [[_Issues Index]]

## Reproduce
```
docker compose run --rm api ruff format --check .
```

## Expected
"26 files already formatted" (quality gate: `ruff format --check .`).

## Actual
"1 file would be reformatted": `tests/unit/test_fake_platform.py:48` (the tiktok 422 assertion). `make lint` only runs `ruff check`, so the gap was missed.

## Suspected location
`tests/unit/test_fake_platform.py` line 47-48; also consider adding `ruff format --check .` to `make lint`.

## Fix
Iteration 2: ran `ruff format`; `make lint` now also runs `ruff format --check .`. See [[Fake Platform]].
