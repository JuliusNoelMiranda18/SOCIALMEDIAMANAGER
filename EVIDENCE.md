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
| Images exact size per platform | `make probe5`; tester's Pillow check in the api container | 1080×1080 and 1600×900 PNG | 2026-11-26 |
| Captions differ and obey platform rules | `bash scripts/probes/stage2_tester.sh` (23 edge cases + 20,000-input fuzz) | X ≤280, 1–2 hashtags, `bad=0` | 2026-11-26 |
| One `llm_calls` row per caption | psql count before/after a 2-platform campaign | +2 rows, integer tokens/cost/latency | 2026-11-26 |
| Malformed input → 4xx, never 500 | `scripts/probes/stage2_4xx.py` (79 cases) | all 4xx; >8 MB → 413 | 2026-11-26 |
| Campaign creation is atomic | injected save failure | 500, no rows, no orphan image files | 2026-11-26 |
| Stage 2 quality gates | `make lint`, `make test`, `make probe`, `make probe5` | clean, 194 passed (98%), all PASS | 2026-11-26 |
| Publish twice + retry after timeout → 1 post per platform | `make probe1` | 11 PASS; key committed before the call (read mid-flight) | 2026-11-26 |
| 429 Retry-After honoured, no hammering | `make probe2`, `/_stats` gaps | `[429,429,201]`, gaps ≥ Retry-After, 5 attempts max | 2026-11-26 |
| No plaintext token in DB or logs | `make probe6` (`pg_dump` + container logs vs `/_tokens`) | 8 PASS, none found | 2026-11-26 |
| Concurrent publishes never mark an accepted post failed | `python3 scripts/probes/stage3_concurrency_stress.py 0.5 8 25 3` (8 runs, 510 entries) | `anomalies=0` | 2026-11-26 |
| Stage 3 quality gates | `make lint`, `make test` | clean, 253 passed (98%) | 2026-11-26 |
