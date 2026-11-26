# Handoff — Stage 2: Data model + content generation

**Goal:** one post in → real images + distinct captions stored.
**Stage start commit:** uncommitted (Stages 0 and 1 are approved but not committed; HEAD is d0e1764)

## Context to read (only these)
- Vault: [[System Map]], [[API]], [[Api Layer]], [[Fake Platform]] (for style only), [[ADR-001 Stack]]
- Source: `app/main.py`, `app/config.py`, `migrations/env.py`, `alembic.ini`, `docker-compose.yml`, `Dockerfile`, `Makefile`, `pyproject.toml`, `.env.example`, `tests/`
- Run everything in containers (host Python is 3.9). The Docker image copies code at build time, so rebuild after code changes: `docker compose up -d --build --wait`.
- Layers: HTTP (`app/api`) → services (`app/services`) → repos (`app/repos`). Content generation lives in `app/content/`. API handlers hold no SQL; services hold no HTTP.

## Design decisions (Senior, follow these)

### Tables (SQLAlchemy 2 models in `app/models.py`, one Alembic migration `0001_initial`)
Set `target_metadata=Base.metadata` in `migrations/env.py`. All ids are `BIGINT` identity. All money, token and latency numbers are integers.
| Table | Columns |
|---|---|
| `posts` | id, title (≤200), body (≤20000), source_url (nullable), source_image (nullable bytea, ≤5 MB), created_at |
| `campaigns` | id, post_id → posts, brand_name (nullable ≤60), created_at |
| `social_post_entries` | id, campaign_id → campaigns, platform (`instagram`\|`x`), caption, image_path, image_width int, image_height int, status text default `draft`, platform_post_id nullable, created_at; UNIQUE(campaign_id, platform) |
| `platform_tokens` | id, platform unique, nonce bytea, ciphertext bytea, created_at. Table only: encryption code is Stage 3 |
| `jobs` | id, kind, payload jsonb, run_at, status default `pending`, attempts int default 0, locked_until nullable, created_at. Table only: worker is Stage 4 |
| `webhook_events` | id, event_id unique, raw_body text, signature_valid bool, received_at. Table only: Stage 5 |
| `llm_calls` | id, entry_id → social_post_entries (nullable), provider, model, prompt_tokens int, completion_tokens int, cost_micro_usd int, latency_ms int, status (`ok`\|`fallback`\|`error`), created_at |

### Endpoints (all validation failures are 4xx, never 500)
- `POST /posts` `{title, body, source_url?, image_b64?}` → 201 `{id, title, created_at}`. Empty title/body or over-length → 422. `image_b64` must decode and open as PNG/JPEG with Pillow, ≤5 MB decoded, ≤25 megapixels (set `Image.MAX_IMAGE_PIXELS`, treat decompression-bomb and decode errors as 422).
- `POST /campaigns` `{post_id, platforms: ["instagram","x"], brand_name?}` → 201 with the campaign and its entries (`id, platform, caption, image_url, image_width, image_height, status`). Unknown `post_id` → 404. Empty list, duplicate or unknown platform → 422. Generates images and captions synchronously inside one DB transaction; if generation fails nothing is saved.
- `GET /campaigns/{id}` → same shape, 404 if missing.
- Images are saved under `MEDIA_DIR` (env, default `/srv/media`), named `{campaign_id}_{platform}.png`, and served by mounting `StaticFiles` at `/media`. `image_url` is `/media/<file>`. In compose, bind-mount `./media:/srv/media` on the api service, add `media/` to `.gitignore`.
- API container runs `alembic upgrade head` before starting uvicorn (so `docker compose up` on a fresh volume works).

### Image pipeline (`app/content/images.py`, Pillow)
- Sizes: Instagram 1080×1080, X 1600×900. Output PNG, exact dimensions.
- Source: the post's `source_image` if present, else a generated title card (solid/gradient background, title text wrapped, kept inside the safe zone).
- Fit with centred cover-crop (`ImageOps.fit`, centering 0.5/0.5) so the subject stays central; all overlay text stays inside a 10% safe margin on every side.
- Optional brand overlay: if `brand_name` is set, draw it bottom-left inside the safe margin on a semi-transparent strip.
- One function per concern: `render(platform, source_image|None, title, brand_name) -> PIL.Image`. No class hierarchy.

### Caption composer (`app/content/captions.py` + `app/content/fragments.py`)
- `fragments.py` holds the shared brand voice string and a per-platform rules dict (max chars: X 280, Instagram 2200; hashtag count X 1–2, Instagram 5–8; tone; format hints). **Prompts are built from these fragments by one function** (`build_prompt(platform, summary)` = brand voice + platform rules + content summary). No prompt text duplicated anywhere else.
- Content summary: deterministic extractive summary (first two sentences, trimmed to ~300 chars). No LLM involved.
- Template fallback: deterministic, differs per platform (X: short, one hook + link text + 1–2 hashtags, ≤280; Instagram: hook, 2–3 short lines, call to action, 5–8 hashtags). Hashtags derived from title words.
- Captions for the two platforms must differ, and must respect the max length.

### LLM wrapper (`app/content/llm.py`)
- ONE function: `generate_caption(platform, summary, entry_id|None, session) -> str`. It: builds the prompt, calls the provider (if any), validates the output (non-empty, within max length, hashtag count within rules), and on timeout / HTTP error / invalid output uses the template fallback. It ALWAYS writes exactly one `llm_calls` row per call (`status` `ok` when the model text was used, `fallback` when the template replaced a failed/invalid model reply or provider is `none`, `error` is not needed beyond that if you can't distinguish: keep it simple but be consistent and documented).
- Providers via env `LLM_PROVIDER`: `none` (default, template only, provider logged as `template`, 0 tokens, 0 cost) or `gemini` (REST `generateContent` through `httpx`, key from `GEMINI_API_KEY`, model from `GEMINI_MODEL`). `LLM_TIMEOUT_SECONDS` default 10.
- Cost: integer micro-USD = `tokens * PRICE_MICRO_USD_PER_MILLION // 1_000_000` using integer price constants in config (default 0 for the free tier).
- Gemini cannot be called live here (no key). Test it with `httpx.MockTransport` (ok reply, timeout, 500, malformed JSON, over-length text). Never put a key in the repo; `.env.example` gets placeholders only.
- Move `httpx` from dev to runtime dependencies. Add `pillow` and `sqlalchemy`/`psycopg` as needed.

## Tasks — Iteration 1
| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 1 | Backend | `app/models.py` + `app/db.py` (engine/session) + Alembic `0001_initial` for all 7 tables; wire `target_metadata`; api container runs `alembic upgrade head` on start | `app/models.py`, `app/db.py`, `migrations/`, `docker-compose.yml` | `docker compose run --rm api alembic upgrade head` ok; `\dt` in db shows 7 tables + alembic_version; `alembic downgrade base` then `upgrade head` works |
| 2 | Backend | Repos + services + API for `POST /posts`, `POST /campaigns`, `GET /campaigns/{id}`; `/media` static mount; bind mount and `.gitignore` entry | `app/api/`, `app/services/`, `app/repos/`, `app/main.py`, `docker-compose.yml`, `.gitignore` | live curl: post → campaign → image URL returns 200 `image/png` |
| 3 | Backend | Image pipeline | `app/content/images.py` | pytest: opens each generated file with Pillow, asserts exact (1080,1080) and (1600,900); overlay text stays inside safe margin (pixel check at margin edge on a plain background); works with and without a source image; tall and wide sources are both cropped to exact size |
| 4 | Backend | Fragments + caption composer + template fallback | `app/content/fragments.py`, `app/content/captions.py` | pytest: X caption ≤280, Instagram within rules, captions differ, hashtag counts in range, deterministic for the same input; prompt built from fragments only (test greps that brand voice string is defined once) |
| 5 | Backend | LLM wrapper with provider `none` and `gemini`, validation, timeout, fallback, cost, `llm_calls` row per call | `app/content/llm.py`, `app/config.py`, `.env.example`, `pyproject.toml` | pytest with MockTransport: ok / timeout / HTTP 500 / malformed JSON / over-length reply → right status and fallback text; exactly one `llm_calls` row per call; cost is an int |
| 6 | Backend | Test database harness: `tests/conftest.py` creates `app_test`, runs migrations, truncates between tests; API tests for the 4xx matrix | `tests/` | pytest: bad title, bad image (not an image, huge, wrong type), unknown post, empty/duplicate/unknown platforms, huge body → 4xx, never 500; valid request → 201 and DB rows exist |
| 7 | Backend | Probe 5: `scripts/probes/probe5_content.sh` + `make probe5`: runs against the live stack, creates a post and campaign, downloads both images, checks dimensions (use `docker compose exec api python -c` with Pillow), checks captions differ, checks `llm_calls` has 2 rows via psql; exit non-zero on failure | `scripts/probes/`, `Makefile` | `make probe5` → all PASS, exit 0 |
| 8 | Backend | `make seed` creates one sample post (curl) and prints its id; vault + docs | `Makefile`, `vault/Modules/`, `vault/Architecture/API.md`, `vault/Architecture/System Map.md`, `README.md`, `docs/design.md` untouched | module notes `Data Model`, `Image Pipeline`, `Caption Composer` exist and link back; API.md lists new endpoints; README documents `make seed` / `make probe5` and the `LLM_PROVIDER` setting |
| 9 | Frontend | none this stage | — | — |

## Stage 2 agent checks (Tester runs these, from PLAN.md)
- dimension test per platform (open the file, exact size), live and in pytest
- captions differ per platform; length and hashtag rules respected
- malformed input → 4xx not 500 (bad JSON, wrong types, NaN-like numbers, huge payloads, non-image base64, zip bomb style image, SQL-looking strings, unicode and emoji titles)
- `llm_calls` row per call (also across a campaign with 2 platforms → 2 rows); cost and token fields are integers
- a failed generation saves nothing (no orphan campaign / entry / image file)
- migrations: upgrade, downgrade, upgrade on a clean DB; `docker compose up` from a fresh volume works
- `ruff check .`, `ruff format --check .`, full pytest, `make probe5`, `make probe` (Stage 1 still green), no secrets (`git grep -iE "api_key|secret=" -- ':!*.example'`; also confirm no real `GEMINI_API_KEY` anywhere)
- Stage exit: probe 5 passes

## Constraints
- ponytail standard: smallest thing that works, no speculative abstractions, no repository/service layers with nothing in them.
- Do not commit. Do not edit `PLAN.md`, `CLAUDE.md`, `docs/design.md`. Do not change `ADR-001` stack.
- Money/token counts are integers. Validation errors are 4xx, never 500.
- Write questions to Blockers instead of guessing.

## Blockers
_Agents write questions here instead of guessing._

## Backend report — Iteration 1
Resumed a stopped run. Reviewed every file left on disk against this handoff; all matched the design, so no code changes were needed beyond docs. Tasks 1–8 done.

**Files (new):** `app/models.py`, `app/db.py`, `app/api/routes.py`, `app/api/schemas.py`, `app/services/{posts,campaigns,errors}.py`, `app/repos/{posts,campaigns}.py`, `app/content/{fragments,captions,images,llm}.py`, `migrations/versions/0001_initial.py`, `tests/conftest.py`, `tests/unit/test_{api,captions,images,llm}.py`, `scripts/probes/probe5_content.sh`, `vault/Modules/{Data Model,Image Pipeline,Caption Composer}.md`
**Files (changed):** `app/main.py`, `app/config.py`, `migrations/env.py`, `docker-compose.yml` (alembic on start, `./media` bind mount), `Makefile` (`seed`, `probe5`), `pyproject.toml` (httpx + pillow runtime), `.env.example` (LLM placeholders), `.gitignore`/`.dockerignore` (`media/`), `README.md`, `vault/Architecture/API.md`, `vault/Architecture/System Map.md`, `vault/Modules/Api Layer.md`

**How to run:** `make up`, then `make seed` (prints post id) and `make probe5`. `LLM_PROVIDER=none` (default) uses templates; `gemini` needs `GEMINI_API_KEY`.

**Commands and results:**
- `ruff format .` (in container) → `63 files left unchanged`
- `docker compose up -d --build --wait` → all 5 containers Healthy
- `make lint` → `All checks passed!` / `46 files already formatted`
- `make test` → `92 passed, 2 warnings in 6.95s` (warnings: TestClient deprecation import, expected DecompressionBombWarning in the 30 MP test)
- `make probe` → all PASS, 0 FAIL lines (Stage 1 still green)
- `make probe5` → 9 PASS lines, `ALL PASS`, exit 0 (re-run after migration cycling: `ALL PASS`)
- `alembic downgrade base && upgrade head && downgrade base && upgrade head && alembic current` → `0001 (head)`; `\dt` → 7 tables + `alembic_version`
- `alembic downgrade base`, then `docker compose restart api` → api Healthy, `make seed` → `post id 1` (api's startup `alembic upgrade head` recreated the schema)
- `git grep -iE "api_key|secret=" -- ':!*.example'` → only PLAN.md, EVIDENCE.md, this handoff (quoting the command) and `client_secret=b` in the Stage 1 fake-platform probe; no real `GEMINI_API_KEY`

**Not done / not verified:**
- Did not run `docker compose down -v` (fresh volume) to avoid wiping the dev DB; equivalent covered by downgrade-to-base + api restart. Tester may run it.
- Gemini never called live (no key); covered by MockTransport tests only.
- Note: `docker compose up` does not restart an already-running api, so after a manual `downgrade base` the api must be restarted to re-migrate.

**Tester focus:** failed generation saves nothing (returns 500 by design for internal render errors, with no rows/files); image validation edge cases (zip-bomb style PNGs, truncated JPEG); `llm_calls` row count per campaign; emoji titles render (boxes, no crash).
## Frontend report — Iteration 1
## Tester — Iteration 1 — FAIL
New re-runnable probes: `bash scripts/probes/stage2_tester.sh` (wraps `scripts/probes/stage2_checks.py` for live content, `scripts/probes/stage2_4xx.py` for the 70-case malformed-input matrix, a host `./media` check, Postgres column types and a forced-failure atomicity test).

| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Fresh boot from an empty volume | PASS | `docker compose down -v && docker compose up -d --build --wait` → `Volume socialmediamanager_pgdata Removed`, all containers `Healthy`; `/health` 200 on :8000 and :9000 |
| api migrated itself | PASS | `\dt` → 7 tables + `alembic_version` (8 rows); `select version_num from alembic_version` → `0001` (no manual alembic run) |
| `make seed` | PASS | `post id 1`, `post id 2`; again after the migration round trip → `post id 1` |
| Migration round trip | PASS | `alembic downgrade base && current && upgrade head && current && downgrade base && upgrade head && current && alembic check` → `0001 (head)` ×2, `No new upgrade operations detected.` (models match the migration) |
| `ruff check .` / `ruff format --check .` (whole repo, mounted) | PASS | `All checks passed!` / `66 files already formatted` (host has no ruff; ran in the api image with `-v $PWD:/repo`) |
| `make lint` | PASS | `All checks passed!` / `46 files already formatted` |
| `make test` + coverage | PASS | `92 passed, 2 warnings`; `pytest --cov=app --cov=fake_platform` → TOTAL 98% (only the `app/worker` stub is uncovered) |
| `make probe` (Stage 1 regression) | PASS | exit 0, 21 PASS, 0 FAIL |
| `make probe5` | PASS | 9 PASS, `ALL PASS`, exit 0 |
| Live post → campaign → GET | PASS | 2 entries; GET body == POST body; status `draft` |
| Image sizes (Pillow in the api container) | PASS | `instagram image exact size (1080, 1080)`, `x image exact size (1600, 900)`, both `200 image/png`; width/height columns match |
| Files on the host under ./media | PASS | `host media/30_instagram.png exists`, `host media/30_x.png exists`; `git check-ignore` → `.gitignore:12:media/` |
| Tall/wide/JPEG/odd-mode sources | PASS | tall 600×2400 and wide 4000×500 PNG → exact sizes, and the red centre subject is at the centre pixel for both platforms; JPEG, L, 1, P, RGBA, LA, I;16, CMYK sources → 201; 25 MP 5.0 MB JPEG → post 0.9 s, campaign 3.2 s, api at 174 MiB |
| Brand overlay | PASS (minor note) | brand vs no-brand pixel diff: bbox (108,896,301,973) IG and (160,746,323,811) X, bottom-left at the margin; the strip's last row is 1 px into the margin → [[ISSUE-005 brand strip bottom row is 1px inside the margin]] |
| Captions: normal input | PASS | captions differ; X ≤280 with 1–2 tags; IG ≤2200 with 5–8 tags; same for emoji, RTL, zero-width, SQL-looking and 200-char titles |
| Captions: long title + URL, URL with `#` | **FAIL** | `x caption <= 280 chars (len=478)`, `(len=480)`; `url with #fragment: x hashtags in 1..2 (n=3)` → [[ISSUE-004 X template caption breaks length and hashtag rules]] |
| llm_calls per call | PASS | `llm_calls +2 for a 2-platform campaign`, `+1 for a 1-platform campaign`, rows linked to both entry ids, provider `template`/status `fallback` |
| Integer token/cost/latency | PASS | Python `int` values; Postgres `completion_tokens:integer cost_micro_usd:integer latency_ms:integer prompt_tokens:integer`; every `id` column is `bigint` |
| 4xx matrix (70 cases) | PASS | `CHECKS FAILED: 0`: bad JSON, empty and array bodies, text/plain, NaN/Infinity/1e400, wrong types, empty/whitespace/201-char titles, 20001-char and 10 MB bodies, NUL, lone surrogate, non-image base64, data: URI, GIF, truncated PNG/JPEG, 30 MP and 60000×60000 tiny-file bomb PNGs, >5 MB decoded, >7 MB string, unknown post 404, empty/duplicate/unknown/wrong-case/10k platforms, brand 61 chars or empty, GET unknown 404, GET abc/0/2^64 422, `/media` traversal 404. Invalid UTF-8 bytes → 400 (still 4xx). No 500 anywhere |
| Atomicity / no orphans | PASS | the `${next_id}_x.png` path is a symlink into a missing dir (no code edit), so the x save fails after the instagram PNG is written: `forced render failure -> 500`, `no new campaign/entry/llm_calls rows`, `no orphan 45_instagram.png`, then the same request → 201. api log: `campaigns.py, line 47 … FileNotFoundError: '/srv/media/45_x.png'`. The 500 body is the plain `Internal Server Error` (no traceback) |
| 500 reachable from user input? | PASS | Not found: every malformed case is 4xx; every valid odd input (8 image modes, 25 MP, emoji/RTL/zero-width/long-word titles and brand names) → 201. The 500 only came from the injected filesystem fault |
| Layering | PASS | `app/api/*` has no SQL (only the `Session` type import); `app/services`, `app/repos` and `app/content` have no fastapi/HTTPException; `BRAND_VOICE` is defined only in `fragments.py` and used only by `captions.build_prompt` |
| Secrets | PASS | `git grep -iE "api_key\|secret=" -- ':!*.example'` → only docs quoting the command, `gemini_api_key: str = ""` in config, `client_secret=b` in the Stage 1 probe; `grep -r "AIza…"` → no hits; `.env` has no `GEMINI_API_KEY`; `.env.example` has an empty `GEMINI_API_KEY=` |
| Review checklist | PASS (notes) | No unbounded retries; Gemini errors fall back to the template and are recorded as `status=fallback` in `llm_calls` (not silently swallowed). Notes: unknown extra JSON fields are ignored and there is no request-size cap (a 30 MB body with a `pad` field → 201); `pyyaml` dev dep is unused (from Stage 0/1); an empty `image_b64: ""` is treated as no image |
| Docs (task 8) | PASS | `Data Model`, `Image Pipeline` and `Caption Composer` link back to [[System Map]] / [[Api Layer]]; System Map lists them; API.md has the 3 endpoints; README has `make seed`, `make probe5`, `LLM_PROVIDER` |

Issues: [[ISSUE-004 X template caption breaks length and hashtag rules]] (blocking), [[ISSUE-005 brand strip bottom row is 1px inside the margin]] (minor)
Stack left running and healthy.

<!-- Senior Dev appends "Tasks — Iteration 2" etc. on FAIL -->

## Tasks — Iteration 2
Senior triage of the Tester's FAIL (loop 2 of 3). ISSUE-004 and ISSUE-005 accepted. I also accept the Tester's note on request size: a 30 MB body returning 201 is an easy memory/DoS hole, so cap it now.

| # | Owner | Task | Files in scope | Acceptance check (command → expected) |
|---|---|---|---|---|
| 10 | Backend | ISSUE-004: fix the X template so the caption ALWAYS respects the rules: `_clip` must never take a negative/zero budget (clamp, and if the link + tags alone exceed the limit, drop/shorten the link text, then the tags down to the minimum), strip `#` (and anything after it) from URLs before they go into captions, and add a final guard that enforces max length and hashtag count for both platforms. Add property-style regression tests: very long title words, long and short URLs, URLs with `#fragment`, empty-ish titles, emoji/unicode; assert X ≤280 and hashtag counts within the fragments rules for every case. | `app/content/captions.py`, `tests/unit/test_captions.py` | `make test` green incl. new cases; tester's repro (two ~100-char title words, `source_url` ≤100 chars, and a `#fragment` URL) gives X ≤280 with 1–2 hashtags |
| 11 | Backend | ISSUE-005: brand strip must stay fully inside the 10% safe margin (account for `rectangle()` including its end row). Test checks the margin row is untouched. | `app/content/images.py`, `tests/unit/test_images.py` | pytest: pixel row at the margin edge unchanged on both platforms |
| 12 | Backend | Request size cap: reject request bodies over 8 MB with 413 (before parsing), on the api app. Keep it tiny (a middleware or uvicorn setting, your call, document it). Test with a >8 MB body → 413 and a normal campaign still 201. | `app/main.py`, `tests/` | pytest + live curl of a 9 MB body → 413, not 500 or 201 |
| 13 | Backend | Close ISSUE-004/005 in `vault/Issues/` (status closed, link the fix); update `Caption Composer` and `Image Pipeline` notes if behaviour changed; mention the body cap in `API.md`. | `vault/` | notes updated |

Rebuild before testing (`docker compose up -d --build --wait`). Run `bash scripts/probes/stage2_tester.sh` too. Do not commit.

## Backend report — Iteration 2
Tasks 10–13 done.

**Files changed:** `app/content/captions.py` (ISSUE-004), `app/content/images.py` (ISSUE-005), `app/main.py` (`BodyLimit` middleware, `MAX_BODY = 8 MB`), `tests/unit/test_captions.py`, `tests/unit/test_images.py`, `tests/unit/test_api.py` (new 413 test; the >5 MB-decoded image test now uses a 1350 px image so its body stays under 8 MB and still hits 422), vault: ISSUE-004/005 (closed + Resolution), `_Issues Index`, `Caption Composer`, `Image Pipeline`, `Api Layer`, `API.md`.

**What changed:**
- ISSUE-004: `_clip` clamps its budget to ≥1; title words over 30 chars are not turned into hashtags (filler tags instead), so link (≤111) + 2 tags (≤63) always leave ≥104 chars for the X hook; `source_url` is cut at the first `#`; `template_caption` re-checks `is_valid` and falls back to `title + minimum filler tags` if it ever fails (checked unreachable over the edge matrix: `guard needed for: []`).
- ISSUE-005: `_brand_strip` rectangle end is `(mx + tw + 2*pad - 1, h - my - 1)`.
- Body cap: pure ASGI middleware. 413 `{"detail": "Request body too large"}` when `Content-Length` > 8 MB (or is not a number), or when the streamed body passes 8 MB (chunked, no `Content-Length`). It buffers ≤8 MB and replays it to the app. Chose this over a uvicorn flag because uvicorn has no body-size setting.

**How to run:** `make up`; then e.g. `curl -XPOST localhost:8000/posts -H 'Content-Type: application/json' --data-binary @9mb_file` → 413.

**Commands and results:**
- `docker compose up -d --build --wait` → all containers Healthy (rebuilt after every code change)
- `ruff format app tests && ruff check app tests && ruff format --check app tests` (mounted repo) → `All checks passed!` / `29 files already formatted`
- `make lint` → **`Found 39 errors`, all in the Tester's `scripts/probes/stage2_4xx.py` (20) and `scripts/probes/stage2_checks.py` (19)**: 38× E501 line too long, 1× B905 `zip()` without `strict=`. These files are new since iteration 1 and are now copied into the image. Zero errors in `app/` and `tests/`. I did not edit Tester-owned probes; see Tester focus.
- `make test` → `194 passed, 2 warnings in 14.99s` (was 92; warnings unchanged: TestClient deprecation, expected DecompressionBombWarning)
- `make probe` → exit 0, 21 PASS, 0 FAIL
- `make probe5` → `ALL PASS`, exit 0
- `bash scripts/probes/stage2_tester.sh` → exit 0, ends `ALL PASS`; ISSUE-004 lines now PASS (`long title + 100-char url: x caption <= 280 chars`, `200-char word + 100-char url: x caption <= 280 chars`, `url with #fragment: x hashtags in 1..2`), no brand-strip NOTE lines. The 4xx matrix prints `CHECKS FAILED: 2`: `body 10 MB -> 413 (want 422)` and `whole payload 30 MB -> 413 (want 201)`. Both are the intended task 12 change; the probe expectations need updating to 413.
- Live curl: 9 MB body → `413`; ISSUE-004 repro 1 (98+99-char title words, 100-char URL) → `201`, X caption 280 chars, 2 hashtags; IG 303 chars, 8 hashtags; repro 2 (`#section` URL) → X `'Hello world launch\nRead more: https://example.com/page\n#hello #world'`, 2 hashtags

**Tester focus:**
- Update `stage2_4xx.py` lines 88 and 109 to expect 413, and fix the 39 ruff errors in `stage2_4xx.py` / `stage2_checks.py` so `make lint` is green again (Tester-owned files).
- 413 on chunked uploads and on a slow client; a body of exactly 8 MB is accepted (limit is `>`).
- A 5 MB decoded image as base64 (~6.7 MB) plus JSON still fits under 8 MB → reaches the 422/201 image checks, not 413.
## Tester — Iteration 2 — PASS
Probe upkeep (Tester-owned): `stage2_4xx.py` rewritten with short `P()`/`C()` helpers (lint clean), the 10 MB and 30 MB cases now expect 413, and new body-cap cases were added. `stage2_checks.py` was reflowed, gets `zip(strict=True)`, and the brand check is now strict (no 1 px tolerance) plus a margin-row pixel compare, and 23 ISSUE-004 edge cases. New `scripts/probes/stage2_caption_fuzz.py` runs 20k random inputs through `template_caption`. `stage2_tester.sh` now also runs the fuzz and curl body-cap checks (Content-Length, chunked, non-numeric CL).

| Check | Result | Evidence (command + key output lines) |
|---|---|---|
| Rebuild + health | PASS | `docker compose up -d --build --wait` → api, db, fake-platform, worker `Healthy`; `/health` 200 on :8000 and :9000 |
| `make lint` | PASS | `All checks passed!` / `49 files already formatted` (was 39 errors) |
| `ruff check .` / `ruff format --check .` (whole repo, mounted) | PASS | `All checks passed!` / `71 files already formatted` |
| `make test` + coverage | PASS | `194 passed, 2 warnings`; `pytest --cov=app --cov=fake_platform` → `TOTAL 586 12 98%` |
| `make probe` (Stage 1) | PASS | exit 0, 21 PASS, 0 FAIL |
| `make probe5` | PASS | 9 PASS, `ALL PASS`, exit 0 |
| `bash scripts/probes/stage2_tester.sh` | PASS | exit 0, 208 PASS lines, `CHECKS FAILED: 0` (live), `CHECKS FAILED: 0` (4xx), `ALL PASS`. Only non-PASS line: `SKIP non-numeric Content-Length (client refused: LocalProtocolError)`, which is covered by curl instead → `PASS curl non-numeric Content-Length -> 4xx` |
| ISSUE-004 original repros (live curl) | PASS | 98+99-char title words + 100-char URL → 201, `x len 280 tags 2`, `instagram len 303 tags 8`; `#section` URL → `x len 68 tags 2 'Hello world launch\nRead more: https://example.com/page\n#hello #world'` |
| ISSUE-004 edge cases (live) | PASS | 23 cases, all `x caption <= 280` and `x hashtags in 1..2`, IG in 5..8, and the captions differ: URL exactly 100 / 101 / 2000 chars, `p#a#b#c#d`, `#` at the 100-char mark, a bare `#`, `%23`, query+`#`, a title of `#one #two … C#`, a title of 200 `#`, 30/31-char words, 40 short words, emoji-only, emoji+long URL, unicode words, underscores, punctuation-only, a body full of `#tags`, a 20000-char one-word body, a title with newlines |
| ISSUE-004 fuzz | PASS | `PASS caption fuzz 20000 inputs x 2 platforms, bad=0` (random mixes of `#`, `##`, `_`, emoji, CJK, 40-char words, `%23`, newlines, with and without URLs) |
| ISSUE-005 margin row | PASS | strict bbox: `instagram brand overlay inside 10% safe zone`, `x … inside 10% safe zone`; `instagram margin row y=972 untouched by brand strip`, `x margin row y=810 untouched by brand strip`; no NOTE lines |
| 8 MB cap: Content-Length | PASS | `body 9 MB with Content-Length -> 413`, `body 8 MB + 1 byte -> 413`, `body exactly 8 MB (limit is >) -> 201`, `body 10 MB -> 413`, `whole payload 30 MB -> 413`; curl `--data-binary @9MB` → 413 |
| 8 MB cap: chunked / slow | PASS | `chunked 9 MB (no Content-Length) -> (413, None)`, `chunked 9 MB to /campaigns -> 413`, `chunked exactly 8 MB -> 201`, `chunked 1 MB valid post -> 201`; curl `Transfer-Encoding: chunked` 9 MB → 413; slow client (3×3 MB chunks, 1 s apart) → `413 3.1s`; 413 body `{"detail":"Request body too large"}` |
| Under-cap images still reach validation | PASS | `image_b64 > 5 MB decoded, body 6.7 MB < cap -> 422`, `image_b64 > 7 MB string (under cap) -> 422`, `valid PNG ok -> 201`; `normal campaign still 201 -> 201` |
| Image sizes | PASS | `instagram image exact size (1080, 1080)`, `x image exact size (1600, 900)`; tall/wide/JPEG sources exact and centred; host `media/71_*.png` exist |
| llm_calls | PASS | `llm_calls +2 for a 2-platform campaign`, `+1 for a 1-platform campaign`, rows linked to entries, Python ints, `template`/`fallback`; Postgres columns `integer`, all ids `bigint` |
| 4xx matrix | PASS | 79 PASS / `CHECKS FAILED: 0`; no 500 anywhere. api log over the whole run: 1 traceback, the injected `FileNotFoundError: '/srv/media/107_x.png'` only |
| Atomicity | PASS | `forced render failure -> 500`, `no new campaign/entry/llm_calls rows`, `no orphan 107_instagram.png`, `same request succeeds after fault removed` (201) |
| Migrations | PASS | `alembic current` → `0001 (head)`; `alembic check` → `No new upgrade operations detected.` (unchanged this iteration; the full round trip passed in iteration 1) |
| Secrets | PASS | `git grep -iE "api_key\|secret=" -- ':!*.example'` → only docs quoting the command, `gemini_api_key: str = ""`, `client_secret=b` (Stage 1 probe); working-tree grep for `AIza…{30}` / `sk-…` → no real key (only the "AIza…" mention in this handoff); `.env.example` has `GEMINI_API_KEY=` (empty) |
| Review checklist | PASS (notes) | Body cap is checked before parsing, buffers ≤8 MB, and non-numeric CL → 4xx. No unbounded retries, and no swallowed errors (fallbacks are recorded in `llm_calls`). Open notes carried from iteration 1: unused `pyyaml` dev dep, `image_b64: ""` treated as no image, and long title words give filler hashtags (`#news #update`) on X, which is acceptable under the rules |

Issues: none new. [[ISSUE-004 X template caption breaks length and hashtag rules]] and [[ISSUE-005 brand strip bottom row is 1px inside the margin]] verified closed.
Stack left running and healthy. Nothing committed.
