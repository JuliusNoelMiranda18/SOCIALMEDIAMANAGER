# PLAN — Multi-Platform Social Campaign Publisher

FlyRank Backend Track capstone (old brief, still accepted). We build the fake
platform server ourselves because the starter was never shipped — say so in the README.

**One-line goal:** one blog post in → per-platform captions + images → scheduled,
idempotent, rate-limit-aware publishing through adapters → status flips only on a
signature-verified webhook.

## Stack (see `vault/Decisions/ADR-001 Stack.md`)

| Layer | Choice |
|---|---|
| API + worker | Python 3.12, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16 (Docker), SQLAlchemy 2 + Alembic migrations |
| Queue / scheduler | Postgres jobs table + `SELECT … FOR UPDATE SKIP LOCKED` worker (durable by construction) |
| Fake platform | Separate small FastAPI app (`fake_platform/`) |
| Images | Pillow |
| Captions | Gemini free tier or local Ollama, template fallback |
| Encryption | `cryptography` AES-GCM, random nonce |
| Frontend | Vite + React + TypeScript (small dashboard) |
| Tests | pytest, httpx, ruff, Playwright (UI smoke) |
| Run | `docker compose up` + `make seed` |

## The loop (every stage)

```
Senior Dev: plan stage → write handoff
   → Backend (ponytail) implements
   → Frontend implements (only stages with UI)
   → Tester verifies (quality + features + probes)
        FAIL → Senior triages → back to owner (max 3 loops, then escalate to you)
        PASS → Senior reviews, updates vault, writes gate report
   → PAUSE: status = AWAITING_APPROVAL. Nothing moves until you run /approve N
```

## Stages

Each stage has: **Goal**, **Scope**, **Owners**, **Agent checks** (what Tester runs),
**Your manual test** (what you run before approving), **Exit**.

---

### Stage 0 — Foundation & design doc
- **Goal:** a repo a stranger can boot.
- **Scope:** folder layout (`app/`, `fake_platform/`, `web/`, `tests/`, `scripts/probes/`),
  `docker-compose.yml` (api, worker, db, fake-platform, web), `.env.example`, `.gitignore`,
  `capstone.yaml`, README skeleton, `EVIDENCE.md`, `BUILDLOG.md`, MIT license,
  `/health` on api and fake-platform, Alembic initialised, one-page `docs/design.md`
  (problem, data model, API surface, layer sketch, one non-goal).
- **Owners:** Senior (design doc), Backend (scaffold).
- **Agent checks:** `docker compose up -d` healthy; `curl /health` = 200 on both apps;
  `ruff check .` clean; no secret in repo (`git grep -iE "api_key|secret=" -- ':!*.example'` empty).
- **Your manual test:** `docker compose up`, open `http://localhost:8000/docs` and
  `http://localhost:9000/docs`.
- **Exit:** design doc approved by you.

### Stage 1 — Fake platform server
- **Goal:** a controllable simulator of Instagram/X.
- **Scope:** `POST /oauth/token`; `POST /v1/posts` honouring `Idempotency-Key`
  (same key → same response, no new post); control endpoints
  `POST /_control` to set: rate-limit mode (429 + `Retry-After`), failure rate,
  "accept-then-drop-response" (timeout after accept), forged-signature mode;
  `GET /_posts` to inspect stored posts; after accepting a post, send an HMAC-SHA256
  signed delivery callback (timestamp + body) to the configured webhook URL.
- **Owners:** Backend.
- **Agent checks:** pytest for each switch; same key twice → 1 stored post;
  429 mode returns header; callback signature verifies with the shared secret.
- **Your manual test:** run `scripts/probes/fake_platform.sh` and read the output.
- **Exit:** every switch demonstrable by curl.

### Stage 2 — Data model + content generation
- **Goal:** one post in → real images + distinct captions stored.
- **Scope:** tables `posts`, `campaigns`, `social_post_entries` (SocialPostEntry shape),
  `platform_tokens` (encrypted), `jobs`, `webhook_events`, `llm_calls` (cost log);
  `POST /posts`, `POST /campaigns`; image pipeline (Instagram 1080×1080, X 1600×900,
  subject kept in safe zone, optional brand overlay); caption composer = shared brand voice +
  platform rules + content summary (fragments in config, no duplicated prompts);
  LLM call behind one function with validation, timeout, cost log, template fallback.
- **Owners:** Backend.
- **Agent checks:** dimension test per platform; captions differ per platform;
  malformed input → 4xx not 500; `llm_calls` row per call.
- **Your manual test:** `POST /campaigns` from Swagger with a sample post, open the
  generated image files, read the captions.
- **Exit:** probe 5 passes.

### Stage 3 — Adapter layer, idempotent publish, rate limits, encrypted tokens
- **Goal:** the heart of the grade.
- **Scope:** `SocialPublisher` interface; `FakeInstagramPublisher`, `FakeXPublisher`;
  idempotency key derived from `(post_id, platform)` and stored before the call;
  timeout-after-accept retried with the same key; 429 → honour `Retry-After` (seconds and
  HTTP-date), exponential backoff with jitter, max attempts; tokens AES-GCM encrypted at
  rest, never logged; app code depends on the interface only.
- **Owners:** Backend.
- **Agent checks:** probe 1 (publish twice + retry after simulated timeout → exactly 1 post
  per platform); probe 2 (429 Retry-After honoured, no hammering — count requests);
  probe 6 (grep DB dump + logs → no plaintext token).
- **Your manual test:** turn on 429 mode via `/_control`, publish, watch worker logs back off.
- **Exit:** probes 1, 2, 6 green.

### Stage 4 — Durable scheduler + worker
- **Goal:** "publish at 9:00" survives crashes.
- **Scope:** jobs table with `run_at`, `status`, `attempts`, `locked_until`; worker claims
  with `SKIP LOCKED`; lease expiry so a killed worker's jobs are reclaimed; partial batch
  safe; `POST /campaigns/{id}/schedule`; a test clock / `advance-time` dev endpoint for demos.
- **Owners:** Backend.
- **Agent checks:** probe 3 — schedule a batch, `docker kill` worker mid-batch, restart →
  all published, zero duplicates (assert via fake platform `GET /_posts`).
- **Your manual test:** schedule 1 minute out, kill the worker container, restart it.
- **Exit:** probe 3 green.

### Stage 5 — Signed webhook + status tracking
- **Goal:** status is trust.
- **Scope:** `POST /webhook/social-delivery`; HMAC over raw body + timestamp, constant-time
  compare, replay window (e.g. 5 min); dedupe by event id; state machine
  `queued → publishing → published | failed`, terminal states never regress;
  forged/modified → 400, status unchanged.
- **Owners:** Backend.
- **Agent checks:** probe 4 (forged → 400 unchanged; valid → published); duplicate
  delivery processed once; stale timestamp rejected.
- **Your manual test:** flip fake platform to forged mode, publish, confirm status stays
  `publishing`; flip back, confirm `published`.
- **Exit:** probe 4 green.

### Stage 6 — Campaign dashboard (frontend)
- **Goal:** the 6-minute demo runs from a UI.
- **Scope:** create campaign from a post; preview images + captions per platform;
  schedule; live status table (poll); publish-history per post; demo controls panel
  (rate-limit toggle, forged webhook, advance time) calling dev endpoints.
- **Owners:** Frontend (skills: ui-ux-pro-max → impeccable → emil-design-eng), Backend
  only for missing endpoints.
- **Agent checks:** Playwright smoke through the demo flow; empty/loading/error states;
  keyboard reachable; no console errors.
- **Your manual test:** do the brief's § 13 demo end to end in the browser.
- **Exit:** demo flow works twice in a row.

### Stage 7 — AI quality layer (your edge)
- **Goal:** turn captions into a measured AI feature.
- **Scope:** eval set (~30 posts) with checks: length limits, hashtag count, banned
  phrases, platform voice rule; grounding check — every number/claim in a caption must
  appear in the source post (planted fake stat must be caught); cost per campaign +
  budget guard; `make eval` prints a pass-rate report.
- **Owners:** Backend, Tester.
- **Agent checks:** `make eval` runs deterministically against fixtures; planted
  hallucination caught; budget guard blocks over-budget calls.
- **Your manual test:** run `make eval`, read the report.
- **Exit:** eval report committed to `docs/eval.md`.

### Stage 8 — Submission pack + demo + CV numbers
- **Goal:** ship.
- **Scope:** README (what, architecture diagram, run + seed, limitations, "fake server built
  in-house" note), `EVIDENCE.md` (one proof per Definition-of-Done box), `BUILDLOG.md`,
  `capstone.yaml` (run/seed/test/base_url/endpoints), clean-machine run test,
  `docs/metrics.md` with the real numbers for CV bullets (duplicates prevented under N
  retries, p95 publish latency, eval pass rate, cost per campaign).
- **Owners:** Senior, Tester.
- **Agent checks:** fresh clone → `docker compose up` → `make seed` → `make test` green;
  every DoD box has evidence.
- **Your manual test:** clone into a new folder and follow only the README.
- **Exit:** you submit.

## Definition of Done ↔ stage map

| Brief requirement | Stage |
|---|---|
| Image variants + dimension test | 2 |
| Captions from fragments | 2 |
| SocialPublisher + 2 adapters | 3 |
| Encrypted tokens | 3 |
| Idempotent publishing | 3 |
| 429 respected | 3 |
| Durable scheduling | 4 |
| Verified webhooks | 5 |
| Status only after verified webhook | 5 |
| Tests for the scary cases | 1–5, 7 |
| README + diagram + pack files | 0, 8 |
