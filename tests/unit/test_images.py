import io

import pytest
from PIL import Image, ImageChops

from app.content.images import MARGIN, SIZES, render


@pytest.mark.parametrize("platform", SIZES)
def test_exact_size_with_and_without_source(platform, tmp_path):
    for src in (None, Image.new("RGB", (300, 200), "red")):
        out = render(platform, src, "Hello world", "Acme")
        f = tmp_path / "o.png"
        out.save(f, "PNG")
        assert Image.open(f).size == SIZES[platform]


@pytest.mark.parametrize("src_size", [(200, 3000), (3000, 200), (50, 50)])
def test_tall_wide_small_sources_cropped_exact(src_size):
    assert render("x", Image.new("RGB", src_size, "blue"), "t", None).size == (1600, 900)


def test_palette_and_rgba_sources_work():
    assert render("instagram", Image.new("P", (10, 10)), "t", None).size == (1080, 1080)
    assert render("instagram", Image.new("RGBA", (10, 10)), "t", None).size == (1080, 1080)


@pytest.mark.parametrize("platform", SIZES)
def test_text_stays_inside_safe_margin(platform):
    w, h = SIZES[platform]
    title = "A very long title " * 12 + "Supercalifragilisticexpialidocious" * 3
    blank = render(platform, None, "", None)
    full = render(platform, None, title, "Brand " * 8)
    diff = ImageChops.difference(blank, full).convert("L").point(lambda v: 255 if v else 0)
    left, top, right, bottom = diff.getbbox()
    assert left >= int(w * MARGIN) - 1 and right <= w - int(w * MARGIN) + 1
    assert top >= int(h * MARGIN) - 1 and bottom <= h - int(h * MARGIN) + 1


@pytest.mark.parametrize("platform", SIZES)
def test_brand_strip_leaves_margin_untouched(platform):
    w, h = SIZES[platform]
    mx, my = int(w * MARGIN), int(h * MARGIN)
    src = Image.new("RGB", (w, h), "white")
    diff = ImageChops.difference(render(platform, src, "", None), render(platform, src, "", "Acme"))
    left, top, right, bottom = diff.getbbox()  # right/bottom are exclusive
    assert left >= mx and top >= my and right <= w - mx and bottom <= h - my


def test_brand_strip_changes_image():
    assert render("x", None, "t", "Acme").tobytes() != render("x", None, "t", None).tobytes()


def test_saved_png_roundtrip():
    b = io.BytesIO()
    render("x", None, "😀 emoji title", None).save(b, "PNG")
    assert Image.open(io.BytesIO(b.getvalue())).format == "PNG"
