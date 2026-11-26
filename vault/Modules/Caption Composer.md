# Caption Composer

**Purpose:** Builds per-platform captions: prompt from shared fragments, optional Gemini call, validation, deterministic template fallback, one `llm_calls` cost row per call.
**Files:** `app/content/fragments.py`, `app/content/captions.py`, `app/content/llm.py`
**Last changed:** Stage 2, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `BRAND_VOICE`, `PLATFORM_RULES` | constants in `fragments.py` | the only prompt text; max chars (X 280, IG 2200), hashtag range (X 1–2, IG 5–8), tone, format |
| `summarize` | `(body) -> str` | first two sentences, ≤300 chars, no LLM |
| `build_prompt` | `(platform, summary) -> str` | brand voice + platform rules + summary |
| `is_valid` | `(platform, text) -> bool` | non-empty, ≤ max chars, hashtag count in range |
| `template_caption` | `(platform, title, summary, url=None) -> str` | deterministic fallback, differs per platform; strips URL `#fragment`, then re-checks `is_valid` with a minimal title + filler-tags guard |
| `generate_caption` | `(platform, summary, entry_id, session, *, title, url, transport=None) -> str` | the one LLM wrapper |

## Connections
- Depends on: [[Data Model]] (`LlmCall`), `httpx`, settings `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `LLM_TIMEOUT_SECONDS`, `PRICE_MICRO_USD_PER_MILLION_INPUT/OUTPUT`
- Used by: `app/services/campaigns.py` ([[Api Layer]]), [[System Map]]

## Invariants
- Exactly one `llm_calls` row per `generate_caption` call (added to the session, committed by the caller's transaction).
- `status`: `ok` = model text used; `fallback` = template used (provider `none`, or timeout / HTTP error / malformed JSON / invalid reply). `error` is not used.
- Provider `none` logs `provider=template, model=template`, 0 tokens, 0 cost.
- Cost is integer micro-USD: `(prompt_tokens*in_price + completion_tokens*out_price) // 1_000_000`.
- API key goes in the `x-goog-api-key` header, never in the URL or logs.

## Tests
- `tests/unit/test_captions.py` — rules per platform, odd titles, long URLs, determinism, captions differ, brand voice defined once; edge matrix (long words, long/short/`#` URLs, emoji, `#`-only titles) × both platforms
- `tests/unit/test_llm.py` — MockTransport: ok, timeout, 500, malformed JSON, empty candidates, over-length, no hashtags, empty; one row each; cost is int

## Gotchas
- Gemini was never called live (no key); only MockTransport tests.
- `#` in titles is stripped from template text so it cannot add extra hashtags; `source_url` is cut at its first `#` for the same reason.
- Title words over 30 chars never become hashtags, so two tags cannot crowd out the X hook ([[ISSUE-004 X template caption breaks length and hashtag rules]]).
