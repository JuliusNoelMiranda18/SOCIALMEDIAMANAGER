"""Stage 2 malformed-input matrix: every case must be 4xx (exact code checked), never 500.

Runs INSIDE the api container:
    docker compose exec -T api python -I - < scripts/probes/stage2_4xx.py
"""

import base64
import io
import json
import struct
import sys
import zlib

import httpx
from PIL import Image

c = httpx.Client(base_url="http://localhost:8000", timeout=120)
FAILS = 0
MB = 1024 * 1024
CAP = 8 * MB  # api request body cap (Stage 2 iteration 2)


def check(name, got, want):
    global FAILS
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name} -> {got}" + ("" if ok else f" (want {want})"))
    FAILS += not ok


def raw(path, body, ctype="application/json"):
    return c.post(path, content=body, headers={"Content-Type": ctype}).status_code


def js(path, obj):
    return c.post(path, json=obj).status_code


def P(**kw):
    """POST /posts with a valid title and body plus overrides."""
    return js("/posts", {"title": T, "body": BODY, **kw})


def C(**kw):
    """POST /campaigns for the probe post plus overrides."""
    return js("/campaigns", {"post_id": pid, "platforms": ["x"], **kw})


def chunked(path, body, size=256 * 1024):
    """Send body with Transfer-Encoding: chunked (no Content-Length)."""

    def gen():
        for i in range(0, len(body), size):
            yield body[i : i + size]

    r = c.post(path, content=gen(), headers={"Content-Type": "application/json"})
    return r.status_code, r.request.headers.get("content-length"), r.text


def png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def b64(b):
    return base64.b64encode(b).decode()


def bomb_png(w, h):
    """Valid 1-bit PNG header claiming w*h pixels, tiny compressed IDAT (all zero rows)."""

    def chunk(t, d):
        crc = struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        return struct.pack(">I", len(d)) + t + d + crc

    ihdr = struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0)
    row = b"\x00" + b"\x00" * ((w + 7) // 8)
    comp = zlib.compressobj(9)
    data = b"".join(comp.compress(row) for _ in range(h)) + comp.flush()
    sig = b"\x89PNG\r\n\x1a\n"
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", data) + chunk(b"IEND", b"")


def padded(n):
    """A valid /posts JSON body of exactly n bytes (extra 'pad' field is ignored)."""
    head = json.dumps({"title": T, "body": BODY, "pad": ""}).encode()
    return head[:-2] + b"a" * (n - len(head)) + head[-2:]


T, BODY = "Title", "Body. More."
ok_png = png(Image.new("RGB", (64, 64), "red"))
jpg = io.BytesIO()
Image.new("RGB", (400, 400), "blue").save(jpg, "JPEG")
gif = io.BytesIO()
Image.new("P", (10, 10)).save(gif, "GIF")
pid = c.post("/posts", json={"title": T, "body": BODY}).json()["id"]

# --- POST /posts
check("bad JSON", raw("/posts", b'{"title": "x", '), 422)
check("empty body", raw("/posts", b""), 422)
check("JSON array body", raw("/posts", b"[]"), 422)
check("text/plain body", raw("/posts", b"title=x", "text/plain"), 422)
# FastAPI body decode error -> 400
check("invalid utf-8 bytes", raw("/posts", b'{"title":"\xff\xfe","body":"b"}'), 400)
check("title number", js("/posts", {"title": 123, "body": BODY}), 422)
check("title null", js("/posts", {"title": None, "body": BODY}), 422)
check("title list", js("/posts", {"title": ["a"], "body": BODY}), 422)
check("title NaN literal", raw("/posts", b'{"title": NaN, "body": "b"}'), 422)
check("title Infinity literal", raw("/posts", b'{"title": Infinity, "body": "b"}'), 422)
check("missing title", js("/posts", {"body": BODY}), 422)
check("missing body", js("/posts", {"title": T}), 422)
check("empty title", P(title=""), 422)
check("whitespace title", P(title="   \n\t"), 422)
check("title 201 chars", P(title="a" * 201), 422)
check("title 200 chars ok", P(title="a" * 200), 201)
check("200 emoji title ok (4-byte chars)", P(title="😀" * 200), 201)
check("empty body text", P(body=""), 422)
check("body 20001 chars", P(body="a" * 20001), 422)
check("body 20000 chars ok", P(body="a" * 20000), 201)
check("body 10 MB -> 413 (body cap)", P(body="a" * 10_000_000), 413)
check("title with NUL", P(title="a\x00b"), 422)
check("lone surrogate escape", raw("/posts", b'{"title": "a\\ud800b", "body": "b"}'), 422)
check("source_url javascript:", P(source_url="javascript:alert(1)"), 422)
check("source_url 3000 chars", P(source_url="https://a.com/" + "a" * 3000), 422)
check("source_url number", P(source_url=5), 422)
check("image_b64 number", P(image_b64=5), 422)
check("image_b64 not base64", P(image_b64="!!!not base64!!!"), 422)
check("image_b64 data: URI prefix", P(image_b64="data:image/png;base64," + b64(ok_png)), 422)
check("image_b64 text, not image", P(image_b64=b64(b"hello world, not an image")), 422)
check("image_b64 GIF (wrong type)", P(image_b64=b64(gif.getvalue())), 422)
check("image_b64 truncated PNG", P(image_b64=b64(ok_png[: len(ok_png) // 2])), 422)
check("image_b64 truncated JPEG", P(image_b64=b64(jpg.getvalue()[:-200])), 422)
check("image_b64 PNG header only", P(image_b64=b64(ok_png[:33])), 422)
check("bomb PNG 6000x5000 (30 MP, tiny file)", P(image_b64=b64(bomb_png(6000, 5000))), 422)
check("bomb PNG 60000x60000 (3.6 GP, tiny)", P(image_b64=b64(bomb_png(60000, 60000))), 422)
big = b64(bomb_png(64, 64) + b"\x00" * (5 * MB + 10))
check(f"image_b64 > 5 MB decoded, body {len(big) / MB:.1f} MB < cap", P(image_b64=big), 422)
check("image_b64 > 7 MB string (under cap)", P(image_b64="A" * 7_000_004), 422)
check("valid PNG ok", P(image_b64=b64(ok_png)), 201)
check("valid JPEG ok", P(image_b64=b64(jpg.getvalue())), 201)
check("whole payload 30 MB -> 413", raw("/posts", padded(30_000_000)), 413)

# --- request body cap (8 MB): Content-Length and chunked
check("body 9 MB with Content-Length -> 413", raw("/posts", padded(9 * MB)), 413)
check("body exactly 8 MB (limit is >) -> 201", raw("/posts", padded(CAP)), 201)
check("body 8 MB + 1 byte -> 413", raw("/posts", padded(CAP + 1)), 413)
code, cl, text = chunked("/posts", padded(9 * MB))
check("chunked 9 MB (no Content-Length) -> 413", (code, cl), (413, None))
check("413 body is JSON detail", text, '{"detail":"Request body too large"}')
code, cl, _ = chunked("/posts", padded(1 * MB))
check("chunked 1 MB valid post -> 201", (code, cl), (201, None))
code, cl, _ = chunked("/posts", padded(CAP))
check("chunked exactly 8 MB -> 201", (code, cl), (201, None))
check("chunked 9 MB to /campaigns -> 413", chunked("/campaigns", padded(9 * MB))[0], 413)
try:
    hdrs = {"Content-Type": "application/json", "Content-Length": "abc"}
    r = c.post("/posts", content=b"{}", headers=hdrs)
    check("non-numeric Content-Length -> 4xx", 400 <= r.status_code < 500, True)
except httpx.HTTPError as e:  # client refused to send it; covered by curl in the shell probe
    print(f"SKIP  non-numeric Content-Length (client refused: {type(e).__name__})")

# --- POST /campaigns
check("campaign bad JSON", raw("/campaigns", b"{not json"), 422)
check("unknown post_id", C(post_id=999_999_999), 404)
check("post_id string", C(post_id="abc"), 422)
check("post_id float 1.5", C(post_id=1.5), 422)
check("post_id null", C(post_id=None), 422)
check("post_id 0", C(post_id=0), 422)
check("post_id -1", C(post_id=-1), 422)
check("post_id 2^63", C(post_id=2**63), 422)
check("post_id 1e400", raw("/campaigns", b'{"post_id": 1e400, "platforms": ["x"]}'), 422)
check("post_id NaN", raw("/campaigns", b'{"post_id": NaN, "platforms": ["x"]}'), 422)
check("post_id -Infinity", raw("/campaigns", b'{"post_id": -Infinity, "platforms": ["x"]}'), 422)
check("post_id SQL string", C(post_id="1; DROP TABLE posts"), 422)
check("platforms missing", js("/campaigns", {"post_id": pid}), 422)
check("platforms empty", C(platforms=[]), 422)
check("platforms duplicate", C(platforms=["x", "x"]), 422)
check("platforms unknown", C(platforms=["tiktok"]), 422)
check("platforms wrong case", C(platforms=["X"]), 422)
check("platforms string", C(platforms="x"), 422)
check("platforms 10k items", C(platforms=["x"] * 10_000), 422)
check("brand_name 61 chars", C(brand_name="b" * 61), 422)
check("brand_name empty", C(brand_name=""), 422)
check("brand_name number", C(brand_name=7), 422)
check("brand_name NUL", C(brand_name="a\x00"), 422)
check("normal campaign still 201", C(platforms=["instagram", "x"]), 201)

# --- GET /campaigns/{id}
check("GET unknown campaign", c.get("/campaigns/999999999").status_code, 404)
check("GET campaign abc", c.get("/campaigns/abc").status_code, 422)
check("GET campaign 0", c.get("/campaigns/0").status_code, 422)
check("GET campaign 2^64", c.get(f"/campaigns/{2**64}").status_code, 422)
check("GET campaign SQL", c.get("/campaigns/1%20OR%201=1").status_code, 422)
check("GET /media traversal", c.get("/media/..%2f..%2fetc%2fpasswd").status_code, 404)

print("CHECKS FAILED:", FAILS)
sys.exit(1 if FAILS else 0)
