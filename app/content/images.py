from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZES = {"instagram": (1080, 1080), "x": (1600, 900)}
MARGIN = 0.10  # safe zone: no overlay text inside this fraction of any edge


def _wrap(text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while font.getlength(word) > max_w:  # a single over-long word: split by characters
            n = max(1, len(word) * max_w // int(font.getlength(word)))
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:n])
            word = word[n:]
        trial = f"{cur} {word}".strip()
        if font.getlength(trial) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def _title_card(size: tuple[int, int], title: str) -> Image.Image:
    w, h = size
    img = ImageOps.colorize(
        Image.linear_gradient("L").resize(size), black=(24, 38, 82), white=(96, 52, 140)
    )
    mx, my = int(w * MARGIN), int(h * MARGIN)
    px = h // 14  # start size, shrink until the block fits the safe zone
    while True:
        font = ImageFont.load_default(px)
        lines = _wrap(title, font, w - 2 * mx)
        line_h = int(px * 1.25)
        if len(lines) * line_h <= h - 2 * my or px <= 16:
            break
        px -= 4
    draw = ImageDraw.Draw(img)
    y = (h - len(lines) * line_h) // 2
    for line in lines:
        draw.text(((w - font.getlength(line)) / 2, y), line, font=font, fill="white")
        y += line_h
    return img


def _brand_strip(img: Image.Image, brand: str) -> Image.Image:
    w, h = img.size
    mx, my = int(w * MARGIN), int(h * MARGIN)
    px = h // 28
    font = ImageFont.load_default(px)
    while font.getlength(brand) > w - 2 * mx - px and px > 10:  # keep text in the safe zone
        px -= 2
        font = ImageFont.load_default(px)
    pad = px // 2
    tw = int(font.getlength(brand))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # rectangle() paints its end row/column too, so stop one pixel short of the margin.
    box = (mx, h - my - px - 2 * pad, mx + tw + 2 * pad - 1, h - my - 1)
    d.rectangle(box, fill=(0, 0, 0, 140))
    d.text((mx + pad, box[1] + pad), brand, font=font, fill="white")
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def render(
    platform: str, source_image: Image.Image | None, title: str, brand_name: str | None
) -> Image.Image:
    size = SIZES[platform]
    if source_image is not None:
        img = ImageOps.fit(source_image.convert("RGB"), size, centering=(0.5, 0.5))
    else:
        img = _title_card(size, title)
    return _brand_strip(img, brand_name) if brand_name else img
