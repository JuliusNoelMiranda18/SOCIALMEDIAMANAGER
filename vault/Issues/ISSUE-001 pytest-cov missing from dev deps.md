# ISSUE-001 pytest-cov missing from dev deps

**Status:** closed
**Stage / iteration:** 0 / 1
**Owner:** backend
**Found by:** tester · [[Stage 0]] · [[_Issues Index]]

## Reproduce
```
docker compose run --rm -T api pytest -q --cov=app --cov=fake_platform
```

## Expected
Tests run with a coverage report (standard Tester quality gate).
## Actual
`pytest: error: unrecognized arguments: --cov=app --cov=fake_platform`

## Suspected location
`pyproject.toml` dev extras (add `pytest-cov`) — [[Api Layer]]

## Resolution
Added `pytest-cov` to the `dev` extras in `pyproject.toml`. The Dockerfile already installs `.[dev]`, so rebuilding the image is enough. Verified: `pytest -q --cov=app --cov=fake_platform` passes with a coverage table (2 passed, 43% total). See [[Api Layer]].
