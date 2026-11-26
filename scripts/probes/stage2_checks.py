"""Stage 2 tester checks. Runs INSIDE the api container against the live api.

Usage (via scripts/probes/stage2_tester.sh):
    docker compose exec -T api python -I - < scripts/probes/stage2_checks.py
Prints PASS/FAIL lines, and "MEDIA <name>" lines for the host-side file check.
"""

import base64
import io
import re
import sys

import httpx
from PIL import Image, ImageChops

sys.path.insert(0, "/srv")
from sqlalchemy import text  # noqa: E402

from app.content.fragments import PLATFORM_RULES  # noqa: E402
from app.db import engine  # noqa: E402

B = "http://localhost:8000"
SIZES = {"instagram": (1080, 1080), "x": (1600, 900)}
FAILS = 0
c = httpx.Client(base_url=B, timeout=60)


def check(name, ok, detail=""):
    global FAILS
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  ({detail})"))
    FAILS += not ok


def scalar(sql):
    with engine.connect() as conn:
        return conn.scalar(text(sql))


def b64(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


def tags(s):
    return len(re.findall(r"#\w+", s))


def post(**kw):
    r = c.post("/posts", json={"title": "Probe post", "body": "First line. Second line.", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def campaign(pid, brand=None, platforms=("instagram", "x")):
    body = {"post_id": pid, "platforms": list(platforms)}
    if brand is not None:
        body["brand_name"] = brand
    r = c.post("/campaigns", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def image(url):
    r = c.get(url)
    return r, Image.open(io.BytesIO(r.content))


def caption_rules(label, entries):
    caps = {e["platform"]: e["caption"] for e in entries}
    check(f"{label}: captions differ", len(set(caps.values())) == len(caps), caps)
    for p, cap in caps.items():
        r = PLATFORM_RULES[p]
        lo, hi = r["hashtags"]
        check(
            f"{label}: {p} caption <= {r['max_chars']} chars",
            0 < len(cap) <= r["max_chars"],
            f"len={len(cap)}",
        )
        check(f"{label}: {p} hashtags in {lo}..{hi}", lo <= tags(cap) <= hi, f"n={tags(cap)}")


# 1. Happy path: post -> campaign -> GET, images, captions, llm_calls
before = scalar("select count(*) from llm_calls")
pid = post(title="Spring Sale Launch", body="We launched a product. It is fast! Come and see.")
camp = campaign(pid, brand="Acme Co")
check("campaign has 2 entries", len(camp["entries"]) == 2)
got = c.get(f"/campaigns/{camp['id']}")
check("GET /campaigns/{id} == POST response", got.status_code == 200 and got.json() == camp)
for e in camp["entries"]:
    p = e["platform"]
    r, img = image(e["image_url"])
    want = SIZES[p]
    ctype = (r.status_code, r.headers["content-type"])
    check(f"{p} image 200 image/png", ctype == (200, "image/png"), ctype)
    check(f"{p} image exact size {want}", img.format == "PNG" and img.size == want, img.size)
    check(f"{p} entry width/height match", (e["image_width"], e["image_height"]) == want)
    check(f"{p} status draft", e["status"] == "draft")
    print(f"MEDIA {e['image_url'].removeprefix('/media/')}")
caption_rules("happy", camp["entries"])
added = scalar("select count(*) from llm_calls") - before
check("llm_calls +2 for a 2-platform campaign", added == 2, added)
ids = sorted(e["id"] for e in camp["entries"])
rows = scalar(
    "select array_agg(entry_id order by entry_id) from llm_calls"
    f" where entry_id in ({ids[0]},{ids[1]})"
)
check("llm_calls rows linked to the 2 entries", list(rows) == ids, rows)
with engine.connect() as conn:
    vals = conn.execute(
        text(
            "select prompt_tokens, completion_tokens, cost_micro_usd, latency_ms, provider, status"
            " from llm_calls order by id desc limit 2"
        )
    ).all()
check(
    "llm_calls token/cost/latency are Python ints",
    all(type(v) is int for row in vals for v in row[:4]),
    vals,
)
check(
    "llm_calls provider=template status=fallback",
    all(r[4:] == ("template", "fallback") for r in vals),
    vals,
)
before1 = scalar("select count(*) from llm_calls")
campaign(pid, platforms=["x"])
added = scalar("select count(*) from llm_calls") - before1
check("llm_calls +1 for a 1-platform campaign", added == 1, added)

# 2. Brand overlay: diff brand vs no-brand renders of the same post. ISSUE-005 is fixed,
# so the strip must stay strictly inside the 10% safe zone (no tolerance).
plain = campaign(pid)
for e_b, e_p in zip(camp["entries"], plain["entries"], strict=True):
    p = e_b["platform"]
    w, h = SIZES[p]
    mx, my = int(w * 0.10), int(h * 0.10)
    img_b = image(e_b["image_url"])[1].convert("RGB")
    img_p = image(e_p["image_url"])[1].convert("RGB")
    box = ImageChops.difference(img_b, img_p).getbbox()
    check(f"{p} brand overlay drawn", box is not None)
    inside = box and box[0] >= mx and box[1] >= my and box[2] <= w - mx and box[3] <= h - my
    check(f"{p} brand overlay inside 10% safe zone", bool(inside), f"bbox={box} m={mx},{my}")
    row_b = img_b.crop((0, h - my, w, h - my + 1)).tobytes()
    row_p = img_p.crop((0, h - my, w, h - my + 1)).tobytes()
    check(f"{p} margin row y={h - my} untouched by brand strip", row_b == row_p)
    check(f"{p} brand overlay in bottom-left", bool(box) and box[0] == mx, box)

# 3. Tall and wide source images: exact size and centred crop
for label, size in (("tall", (600, 2400)), ("wide", (4000, 500))):
    src = Image.new("RGB", size, (0, 0, 255))
    cx, cy = size[0] // 2, size[1] // 2
    src.paste((255, 0, 0), (cx - 40, cy - 40, cx + 40, cy + 40))  # red subject in the middle
    camp_i = campaign(post(title=f"{label} image", image_b64=b64(src)))
    for e in camp_i["entries"]:
        _, img = image(e["image_url"])
        w, h = SIZES[e["platform"]]
        check(f"{label} source -> {e['platform']} exact size", img.size == (w, h), img.size)
        px = img.convert("RGB").getpixel((w // 2, h // 2))
        check(f"{label} source -> {e['platform']} subject centred", px[0] > 200 and px[2] < 60, px)
jpg = Image.new("RGB", (900, 1600), (10, 200, 10))
camp_j = campaign(post(title="jpeg tall", image_b64=b64(jpg, "JPEG")), brand="Brand")
sizes = [image(e["image_url"])[1].size for e in camp_j["entries"]]
check("JPEG source campaign sizes", sizes == [SIZES[e["platform"]] for e in camp_j["entries"]])

# 4. Unicode / emoji / SQL-looking strings are stored verbatim and render
TITLES = (
    "Launch 🚀🔥 día ñandú 日本語テキスト",
    "'; DROP TABLE posts; --",
    "🚀" * 200,
    "x" * 200,
    "​" * 50 + "zero width",
    "مرحبا بالعالم RTL",
)
for title in TITLES:
    r = c.post("/posts", json={"title": title, "body": "' OR 1=1 --. Body 🚀 two."})
    ok = r.status_code == 201
    cr = None
    if ok:
        body = {
            "post_id": r.json()["id"],
            "platforms": ["instagram", "x"],
            "brand_name": "🚀 Ñ'; --",
        }
        cr = c.post("/campaigns", json=body)
    codes = (r.status_code, cr and cr.status_code)
    check(f"unicode/sql title {title[:20]!r} -> 201/201", codes == (201, 201), codes)
    if codes == (201, 201):
        check(f"title {title[:20]!r} stored verbatim", r.json()["title"] == title.strip())
        caption_rules(f"title {title[:12]!r}", cr.json()["entries"])
check("posts table still exists after SQL-looking input", scalar("select count(*) from posts") > 0)

# 5. Caption rules with user-controlled source_url and long titles (ISSUE-004 regression)
long_title = "a" * 98 + " " + "b" * 99
base = "https://example.com/"
CASES = (
    ("url with #fragment", {"source_url": base + "page#section"}),
    ("long title + 100-char url", {"title": long_title, "source_url": base + "x" * 80}),
    ("200-char word + 100-char url", {"title": "x" * 200, "source_url": base + "y" * 80}),
    ("url exactly 100 chars", {"title": long_title, "source_url": base + "z" * 80}),
    ("url 101 chars", {"title": long_title, "source_url": base + "z" * 81}),
    ("url 2000 chars", {"title": long_title, "source_url": base + "q" * 1980}),
    ("url many #frags", {"source_url": base + "p#a#b#c#d"}),
    (
        "url #frag at 100 chars",
        {"title": long_title, "source_url": base + "f" * 60 + "#" + "g" * 30},
    ),
    ("url only #", {"source_url": base + "#"}),
    ("url %23 encoded", {"title": "Hash test", "source_url": base + "p%23tag%23two"}),
    ("url query + #", {"source_url": base + "p?a=1&b=2#x"}),
    ("title with #tags", {"title": "#one #two #three #four C# launch"}),
    ("title only #", {"title": "#" * 200}),
    ("title 30/31-char words", {"title": "a" * 30 + " " + "b" * 31 + " " + "c" * 30}),
    ("title many short words", {"title": " ".join(f"w{i:03d}" for i in range(40))}),
    ("title emoji only", {"title": "🚀🔥🎉" * 60}),
    ("emoji + long url", {"title": "🚀" * 200, "source_url": base + "e" * 80}),
    ("title unicode words", {"title": "Ñandú café über straße 日本語テキスト " * 5}),
    ("title underscores", {"title": "snake_case_word another_one third_word"}),
    ("title punctuation", {"title": "!!! ??? ... --- ,,, ;;;"}),
    ("body with #tags", {"body": "#a #b #c #d #e #f #g #h #i. Second #j #k."}),
    ("body 20000 one word", {"body": "z" * 20000}),
    ("title newlines", {"title": "line one\nline two\n#three"}),
)
for label, kw in CASES:
    caption_rules(label, campaign(post(**kw))["entries"])
print("MEDIA_DONE")
print("CHECKS FAILED:", FAILS)
sys.exit(1 if FAILS else 0)
