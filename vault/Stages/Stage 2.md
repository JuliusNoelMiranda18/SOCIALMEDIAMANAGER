# Stage 2 — Data model + content generation

**Status:** AWAITING_APPROVAL · **Loops used:** 2/3 · **Date:** 2026-11-26

## Built
- 7 tables in one Alembic migration `0001_initial` (posts, campaigns, social_post_entries, platform_tokens, jobs, webhook_events, llm_calls); the api migrates itself on start. See [[Data Model]].
- `POST /posts` (optional `image_b64`), `POST /campaigns`, `GET /campaigns/{id}`; images served at `/media/…` and saved on your machine under `./media/`. See [[Api Layer]], [[API]].
- Image pipeline: Instagram 1080×1080, X 1600×900, centred crop, title card when there's no image, text and brand strip inside a 10% safe margin. See [[Image Pipeline]].
- Caption composer: shared brand voice + per-platform rules in one fragments file, deterministic template captions that differ per platform. See [[Caption Composer]].
- LLM wrapper: provider `none` (template, default) or `gemini`; validates replies, falls back to the template, writes one `llm_calls` row per caption with integer tokens/cost/latency.
- 8 MB request body cap (413). Campaign creation is all-or-nothing (rows and image files).
- `make seed`, `make probe5`; tester probes `scripts/probes/stage2_*`.

## Tester evidence
| Check | Result | Evidence |
|---|---|---|
| Fresh boot (`down -v`, `up --wait`), api self-migrates | PASS | 7 tables + alembic_version at 0001 |
| Migration down/up round trip, `alembic check` | PASS | no drift |
| Image sizes exact (live + pytest) | PASS | 1080×1080, 1600×900 PNG, tall/wide sources |
| Captions differ, X ≤280, hashtags within rules | PASS | 23 edge cases + 20,000-input fuzz, `bad=0` |
| `llm_calls` row per call, integer columns | PASS | +2 per 2-platform campaign |
| 4xx matrix, never 500 | PASS | 79 cases; >8 MB → 413 (also chunked) |
| Failed generation saves nothing | PASS | injected fault → 500, no rows, no orphan files |
| `ruff check` + `format --check`, `make test`, `make probe`, `make probe5` | PASS | clean, 194 passed (98% cov), all PASS |
| Secret grep, no Gemini key anywhere | PASS | clean |

Full output: [[Current Handoff]] (Tester, Iterations 1 and 2).

## Your manual test (do this before /approve 2)
1. `cd /Users/jouleused/Desktop/SOCIALMEDIAMANAGER && docker compose up -d --build --wait`
2. `make seed` and note the printed post id (or create one in Swagger, step 3).
3. Open http://localhost:8000/docs → `POST /campaigns` → Try it out → body `{"post_id": <id>, "platforms": ["instagram", "x"], "brand_name": "FlyRank"}` → Execute. Expect 201.
4. Read the two captions in the response: they should differ, and the X one should be short with 1–2 hashtags.
5. Open the images: `open media/` (Finder) or http://localhost:8000/media/<campaign_id>_instagram.png and `_x.png`. Instagram should be square, X wide, brand name bottom-left.
6. Optional: `make probe5` for the automated version.

## Known limitations
- Captions come from the template unless you set `LLM_PROVIDER=gemini` and a key in `.env`. Gemini was only tested with mocked HTTP responses, never live.
- The Gemini call runs inside the DB transaction (holds a connection up to the 10 s timeout). Fine at this scale; revisit if campaigns get slow.
- Emoji in titles render as boxes on images (the default font has no emoji); they don't crash.
- `image_b64: ""` is treated as "no image". `pyyaml` dev dependency is unused.

## Issues closed / still open
- Closed: [[ISSUE-004 X template caption breaks length and hashtag rules]], [[ISSUE-005 brand strip bottom row is 1px inside the margin]]. Open: none.

## Dead ends logged
None.

## Links
[[00 Home]] · [[_Stages Index]] · [[System Map]] · previous: [[Stage 1]]

## Next stage preview
Stage 3: `SocialPublisher` interface with FakeInstagram/FakeX adapters, idempotency keys from `(post_id, platform)` stored before the call, 429 `Retry-After` + backoff, AES-GCM encrypted tokens.

## Approval
_Approved by user on <date>_
