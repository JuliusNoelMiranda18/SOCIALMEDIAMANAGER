# Stage 0 — Foundation & design doc

**Status:** AWAITING_APPROVAL · **Loops used:** 2/3 · **Date:** 2026-11-24

## Built
- Folder layout: `app/` (api, services, repos, worker), `fake_platform/`, `web/` (nginx placeholder), `tests/`, `scripts/probes/`, `migrations/`
- `docker-compose.yml`: db (postgres:16), api :8000, worker, fake-platform :9000, web :5173
- `/health` on api and fake-platform; Pydantic v2 settings; Alembic initialised (no tables)
- `.env.example`, `Makefile` (up/down/test/lint/seed), `pyproject.toml`, `Dockerfile`, `capstone.yaml`
- README skeleton, `EVIDENCE.md`, `BUILDLOG.md`, MIT `LICENSE`
- `docs/design.md` (problem, data model, API surface, layers, non-goal)

## Tester evidence
| Check | Result | Evidence |
|---|---|---|
| Clean boot, all services up | PASS | `down -v` then `docker compose up -d --build --wait` |
| `/health` 200 on 8000 and 9000 | PASS | `{"status":"ok"} 200` |
| `ruff check .` | PASS | All checks passed |
| `pytest -q --cov=...` | PASS | 2 passed, 43% total |
| `alembic current` | PASS | exit 0 |
| Secret grep | PASS | only docs quoting the command match |
| Design doc sections | PASS | all five present |

Full output: [[Current Handoff]] (Tester, Iteration 1 and 2).

## Your manual test (do this before /approve 0)
1. `cd /Users/jouleused/Desktop/SOCIALMEDIAMANAGER && cp .env.example .env && docker compose up --build`
2. Open http://localhost:8000/docs and http://localhost:9000/docs and try `GET /health` in each.
3. Read `docs/design.md` and confirm the design is what you want to build.

## Known limitations
- Dependencies are unpinned.
- Worker only logs "worker idle"; no SIGTERM handling (Stage 4).
- `web` is a static placeholder until Stage 6.
- Coverage is 43% because config and worker are not exercised yet.

## Issues closed / still open
- Closed: [[ISSUE-001 pytest-cov missing from dev deps]]. Open: none.

## Dead ends logged
None.

## Next stage preview
Stage 1: the fake platform server (OAuth token, idempotent `POST /v1/posts`, `/_control` switches, signed delivery callback).

## Approval
_Approved by user on 2026-11-24_
