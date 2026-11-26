# Image Pipeline

**Purpose:** Renders one exact-size PNG per platform from the post's source image or a generated title card, with an optional brand strip.
**Files:** `app/content/images.py`
**Last changed:** Stage 2, 2026-11-26

## Key functions / classes
| Name | Signature | What it does |
|---|---|---|
| `SIZES` | `{"instagram": (1080,1080), "x": (1600,900)}` | target sizes |
| `MARGIN` | `0.10` | safe zone on every edge; no overlay text inside it |
| `render` | `(platform, source_image \| None, title, brand_name) -> PIL.Image` | cover-crop (`ImageOps.fit`, centering 0.5/0.5) or title card, then brand strip |
| `_title_card` | `(size, title)` | gradient background, wrapped title, font shrinks until it fits the safe zone |
| `_brand_strip` | `(img, brand)` | semi-transparent strip bottom-left inside the safe margin |

## Connections
- Depends on: Pillow
- Used by: `app/services/campaigns.py` ([[Api Layer]]), [[System Map]]

## Invariants
- Output size is exactly `SIZES[platform]`.
- All overlay text and the brand strip lie inside the 10% margin (pixel-diff tests; the strip's last row/column is `h - my - 1` / inside `w - mx`).
- Uploaded images are validated in `app/services/posts.py`: PNG/JPEG only, ≤5 MB decoded, ≤25 MP (`Image.MAX_IMAGE_PIXELS`), decode errors → 422.

## Tests
- `tests/unit/test_images.py` — exact sizes with/without source, tall/wide/small sources, P/RGBA modes, text inside safe margin, brand strip leaves margin untouched (no tolerance), PNG round trip

## Gotchas
- `ImageDraw.rectangle` paints its end coordinates; end boxes at `edge - 1` ([[ISSUE-005 brand strip bottom row is 1px inside the margin]]).
- Pillow's default font has no emoji glyphs; emoji titles render as boxes but do not fail.
- Files are written as `{campaign_id}_{platform}.png` under `MEDIA_DIR` and deleted again if the campaign transaction fails.
