# ISSUE-004 X template caption breaks length and hashtag rules

**Status:** closed (Stage 2, iteration 2)
**Stage / iteration:** 2 / 1
**Owner:** backend
**Found by:** tester · [[Stage 2]] · [[_Issues Index]]

Two defects, both in the X branch of `template_caption`, both reachable from ordinary user input to `POST /posts`. The bad captions are stored in `social_post_entries` with 201. That breaks the handoff rule "captions must respect the max length" and the docstring "Always satisfies is_valid". These captions would then be rejected by the platform at publish time (Stage 3).

## Reproduce
```
bash scripts/probes/stage2_tester.sh      # live section 5, or by hand:
curl -s -XPOST localhost:8000/posts -H 'Content-Type: application/json' \
  -d '{"title":"'$(printf 'a%.0s' {1..98})' '$(printf 'b%.0s' {1..99})'","body":"One. Two.","source_url":"https://example.com/'$(printf 'x%.0s' {1..80})'"}'
curl -s -XPOST localhost:8000/campaigns -H 'Content-Type: application/json' -d '{"post_id":<id>,"platforms":["x"]}'

curl -s -XPOST localhost:8000/posts -H 'Content-Type: application/json' \
  -d '{"title":"Hello world launch","body":"One. Two.","source_url":"https://example.com/page#section"}'
# then POST /campaigns for that post
```

## Expected
X caption is at most 280 chars and has 1 or 2 hashtags (`PLATFORM_RULES["x"]`), for any valid post.

## Actual
```
FAIL  long title + 100-char url: x caption <= 280 chars  (len=478)
FAIL  200-char word + 100-char url: x caption <= 280 chars  (len=480)
FAIL  url with #fragment: x hashtags in 1..2  (n=3)
```
1. **Length:** `hook = _clip(title, 280 - len(link) - len(tags) - 2)`. A title with long words gives long hashtags (up to about 200 chars for two tags), and a URL of 100 chars or less gives a link of up to 111 chars, so the budget goes negative (about -33). `_clip(text, n)` with a negative `n` slices `text[: n - 1]`, which keeps most of the title instead of shortening it. The result is 478 to 480 chars.
2. **Hashtags:** the `source_url` goes into the caption unchanged, so a URL fragment (`#section`) counts as a third hashtag under `#\w+`. Title and summary have `#` stripped, but the URL does not.

## Suggested fix
Cap the hashtag length (or drop the link when space is short), clamp `_clip` to `n >= 1`, and leave out a URL that contains `#` (or strip the fragment). Then assert `is_valid(platform, template_caption(...))` in a property-style unit test over long titles, long URLs and URLs containing `#`.

## Suspected location
`app/content/captions.py` `template_caption` (X branch) and `_clip`. See [[Caption Composer]].

## Resolution
Fixed in `app/content/captions.py` (see [[Caption Composer]]):
- `_clip` clamps its budget to at least 1.
- Title words over 30 chars are not used as hashtags (filler tags instead), so link (≤111) + two tags (≤63) leave ≥104 chars for the hook.
- `source_url` is cut at the first `#` before it goes into any caption.
- `template_caption` re-checks `is_valid` and, if it ever fails, returns `title + minimum filler tags` (unreachable for the tested inputs).
Regression: `tests/unit/test_captions.py::test_template_rules_hold_for_edge_inputs` (98 cases) and `test_url_fragment_is_stripped`. Live repro: X 280 chars / 2 tags; fragment URL → 2 tags.
