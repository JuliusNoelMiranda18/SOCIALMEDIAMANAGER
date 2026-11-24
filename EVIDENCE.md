# Evidence

| Claim | Command | Result | Date |
|---|---|---|---|
| Stack boots from clean state | `docker compose down -v && docker compose up -d --build --wait` | db, api, fake-platform healthy; worker and web running | 2026-11-24 |
| Both apps healthy | `curl -s -w ' %{http_code}' localhost:8000/health` and `:9000/health` | `{"status":"ok"} 200` on both | 2026-11-24 |
| Lint clean | `docker compose run --rm api ruff check .` | All checks passed | 2026-11-24 |
| Tests + coverage | `docker compose run --rm api pytest -q --cov=app --cov=fake_platform` | 2 passed, total 43% | 2026-11-24 |
| Migrations wired | `docker compose run --rm api alembic current` | exit 0 | 2026-11-24 |
| No secrets in repo | `git grep -iE "api_key\|secret=" -- ':!*.example'` | only PLAN.md and the handoff, which quote the command | 2026-11-24 |
| Same Idempotency-Key twice → 1 post | `bash scripts/probes/fake_platform.sh`; 10 concurrent same-key requests then `GET /_posts` | identical 201s, exactly 1 stored post | 2026-11-24 |
| 429 mode sends Retry-After | `POST /_control {"rate_limit":{"enabled":true,"retry_after_seconds":7}}` then `POST /v1/posts` | 429 with `Retry-After: 7`, nothing stored | 2026-11-24 |
| Accept-then-drop is safe to retry | probe drop mode, `curl -m 2` | client exit 28, post exists, retry returns it, still 1 post | 2026-11-24 |
| Callback signature verifies; forged does not | tester's own receiver + HMAC-SHA256 recompute with `WEBHOOK_SECRET` | normal `sig_valid=True`, forged `False` | 2026-11-24 |
| No 500 on bad control input | `curl` NaN / Infinity / -Infinity to `/_control` | 422 each, state unchanged | 2026-11-24 |
| Stage 1 quality gates | `make lint`, `make test`, `make probe` | lint + format clean, 16 passed, probe exit 0 | 2026-11-24 |
