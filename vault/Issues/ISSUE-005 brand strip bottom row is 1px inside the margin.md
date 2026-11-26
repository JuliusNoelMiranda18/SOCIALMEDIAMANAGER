# ISSUE-005 brand strip bottom row is 1px inside the margin

**Status:** closed (Stage 2, iteration 2)
**Stage / iteration:** 2 / 1
**Owner:** backend
**Found by:** tester · [[Stage 2]] · [[_Issues Index]]

## Reproduce
```
bash scripts/probes/stage2_tester.sh
# section 2 compares the brand and no-brand renders of the same post (ImageChops.difference bbox)
```

## Expected
The whole overlay stays inside the 10% safe zone: the last row is at most `h - my - 1`.

## Actual
```
NOTE  instagram brand strip bottom row y=972 is 1px into the margin   (h=1080, my=108)
NOTE  x brand strip bottom row y=810 is 1px into the margin           (h=900,  my=90)
```
`ImageDraw.rectangle(box)` includes its end coordinates, so `box = (..., h - my)` paints row `h - my`, which is the first row of the margin. The right edge has the same off-by-one. The brand text itself is inside the safe zone. Only the semi-transparent strip edge is affected.

## Suspected location
`app/content/images.py` `_brand_strip`: use `h - my - 1` and `mx + tw + 2 * pad - 1` for the rectangle end. See [[Image Pipeline]].

## Resolution
Fixed in `app/content/images.py` `_brand_strip`: rectangle end is `(mx + tw + 2*pad - 1, h - my - 1)`. Regression: `tests/unit/test_images.py::test_brand_strip_leaves_margin_untouched` (brand vs no-brand diff bbox, exclusive edges, no tolerance) on both platforms. See [[Image Pipeline]].
