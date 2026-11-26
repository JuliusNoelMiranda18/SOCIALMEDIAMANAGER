import base64
import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.config import settings
from app.main import app
from app.models import Campaign, LlmCall, Post, SocialPostEntry

client = TestClient(app, raise_server_exceptions=False)


def b64_img(fmt="PNG", size=(40, 30)):
    b = io.BytesIO()
    Image.new("RGB", size, "green").save(b, fmt)
    return base64.b64encode(b.getvalue()).decode()


def post(**kw):
    return client.post("/posts", json={"title": "Spring Sale", "body": "Big news. Come see.", **kw})


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_happy_path(db):
    p = post(image_b64=b64_img(), source_url="https://example.com/x")
    assert p.status_code == 201
    r = client.post(
        "/campaigns",
        json={"post_id": p.json()["id"], "platforms": ["instagram", "x"], "brand_name": "Acme"},
    )
    assert r.status_code == 201
    e = {x["platform"]: x for x in r.json()["entries"]}
    assert (e["instagram"]["image_width"], e["x"]["image_height"]) == (1080, 900)
    assert e["instagram"]["caption"] != e["x"]["caption"]
    img = client.get(e["x"]["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(img.content)).size == (1600, 900)
    assert client.get(f"/campaigns/{r.json()['id']}").json() == r.json()
    assert count(db, LlmCall) == 2 and count(db, SocialPostEntry) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "", "body": "b"},
        {"title": "  ", "body": "b"},
        {"title": "t", "body": ""},
        {"title": "t" * 201, "body": "b"},
        {"title": "t", "body": "b" * 20001},
        {"title": 5, "body": "b"},
        {"title": None, "body": "b"},
        {"title": "t\x00", "body": "b"},
        {"title": "t", "body": "b", "source_url": "javascript:x"},
        {"title": "t", "body": "b", "image_b64": "!!!not base64"},
        {"title": "t", "body": "b", "image_b64": base64.b64encode(b"hello").decode()},
        {"title": "t", "body": "b", "image_b64": b64_img("GIF")},
        {"title": "t", "body": "b", "image_b64": b64_img("BMP")},
        {
            "title": "t",
            "body": "b",
            "image_b64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 50).decode(),
        },
        {"title": "t", "body": "b", "image_b64": 12},
        {"title": "t", "body": "b", "image_b64": "A" * 7_000_001},
    ],
)
def test_bad_posts_are_422(db, payload):
    assert client.post("/posts", json=payload).status_code == 422
    assert count(db, Post) == 0


def test_bad_json_and_nonjson():
    assert (
        client.post(
            "/posts", content=b"{nope", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/posts", content=b"NaN", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )


def test_oversize_and_huge_pixel_images_422():
    big = io.BytesIO()
    # 1350 px keeps the base64 body under the 8 MB request cap, so this hits the 422 path.
    Image.frombytes("RGB", (1350, 1350), os.urandom(1350 * 1350 * 3)).save(big, "PNG")
    assert len(big.getvalue()) > 5 * 1024 * 1024
    r = post(image_b64=base64.b64encode(big.getvalue()).decode())
    assert r.status_code == 422  # over 5 MB decoded (or over the b64 cap)
    flat = io.BytesIO()
    Image.new("1", (6000, 5000)).save(flat, "PNG")  # 30 MP, tiny file
    assert len(flat.getvalue()) < 5 * 1024 * 1024
    assert post(image_b64=base64.b64encode(flat.getvalue()).decode()).status_code == 422


def test_lone_surrogate_escape_is_422(db):
    h = {"content-type": "application/json"}
    r = client.post("/posts", content=b'{"title": "\\ud800", "body": "b"}', headers=h)
    assert r.status_code == 422 and count(db, Post) == 0


def test_sql_unicode_titles_ok():
    for t in ["x'); DROP TABLE posts;--", "😀 emoji ✓ 日本語"]:
        assert client.post("/posts", json={"title": t, "body": "b"}).status_code == 201


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"post_id": 999, "platforms": ["x"]}, 404),
        ({"post_id": 2**63, "platforms": ["x"]}, 422),
        ({"post_id": 0, "platforms": ["x"]}, 422),
        ({"post_id": 1.5, "platforms": ["x"]}, 422),
        ({"post_id": "a", "platforms": ["x"]}, 422),
        ({"post_id": 1, "platforms": []}, 422),
        ({"post_id": 1, "platforms": ["x", "x"]}, 422),
        ({"post_id": 1, "platforms": ["tiktok"]}, 422),
        ({"post_id": 1, "platforms": "x"}, 422),
        ({"post_id": 1, "platforms": ["x"], "brand_name": "b" * 61}, 422),
        ({"platforms": ["x"]}, 422),
    ],
)
def test_bad_campaigns(db, payload, code):
    post()  # post id 1 exists
    assert client.post("/campaigns", json=payload).status_code == code
    assert count(db, Campaign) == 0


@pytest.mark.parametrize("cid", ["999", "0", "-1", "abc", str(2**63)])
def test_get_campaign_bad_ids(cid):
    assert client.get(f"/campaigns/{cid}").status_code in (404, 422)
    assert client.get("/campaigns/999").status_code == 404


def test_failed_generation_saves_nothing(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    pid = post().json()["id"]
    import app.services.campaigns as svc

    calls = []

    def boom(platform, *a, **k):
        calls.append(platform)
        if len(calls) == 2:
            raise RuntimeError("render failed")
        return Image.new("RGB", (10, 10))

    monkeypatch.setattr(svc, "render", boom)
    media = tmp_path
    r = client.post("/campaigns", json={"post_id": pid, "platforms": ["instagram", "x"]})
    assert r.status_code == 500
    assert count(db, Campaign) == count(db, SocialPostEntry) == count(db, LlmCall) == 0
    assert list(media.iterdir()) == []


def test_body_over_8mb_is_413_before_parsing(db):
    h = {"Content-Type": "application/json"}
    big = b'{"title": "t", "body": "b", "pad": "' + b"a" * (8 * 1024 * 1024) + b'"}'
    assert client.post("/posts", content=big, headers=h).status_code == 413
    assert client.post("/posts", content=b"not json" * 2_000_000, headers=h).status_code == 413

    def chunks():  # no Content-Length: the streamed size is still counted
        for _ in range(9):
            yield b"a" * 1024 * 1024

    assert client.post("/posts", content=chunks(), headers=h).status_code == 413
    pid = post().json()["id"]
    r = client.post("/campaigns", json={"post_id": pid, "platforms": ["x", "instagram"]})
    assert r.status_code == 201
