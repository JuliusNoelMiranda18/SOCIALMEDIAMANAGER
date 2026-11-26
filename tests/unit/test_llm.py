import json

import httpx
import pytest

from app.config import settings
from app.content.llm import generate_caption
from app.models import LlmCall


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "price_micro_usd_per_million_input", 100_000)
    monkeypatch.setattr(settings, "price_micro_usd_per_million_output", 400_000)


def _reply(text):
    body = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 50},
    }
    return httpx.Response(200, json=body)


def _gen(db, handler):
    t = httpx.MockTransport(handler)
    out = generate_caption("x", "summary", None, db, title="Spring Sale", transport=t)
    db.commit()
    rows = db.query(LlmCall).all()
    assert len(rows) == 1
    return out, rows[0]


def test_none_provider(db):
    out, row = generate_caption("x", "s", None, db, title="Spring Sale"), None
    db.commit()
    row = db.query(LlmCall).one()
    assert out.startswith("Spring Sale")
    assert (row.provider, row.status, row.prompt_tokens, row.cost_micro_usd) == (
        "template",
        "fallback",
        0,
        0,
    )


def test_ok(db, gemini):
    out, row = _gen(db, lambda r: _reply("Great news! #launch"))
    assert out == "Great news! #launch"
    assert (row.provider, row.status, row.prompt_tokens, row.completion_tokens) == (
        "gemini",
        "ok",
        1000,
        50,
    )
    assert row.cost_micro_usd == (1000 * 100_000 + 50 * 400_000) // 1_000_000
    assert isinstance(row.cost_micro_usd, int)


def test_key_sent_in_header_not_body(db, gemini):
    seen = {}

    def h(r):
        seen["key"], seen["body"] = r.headers["x-goog-api-key"], r.content
        return _reply("Hi #a")

    _gen(db, h)
    assert seen["key"] == "test-key" and b"test-key" not in seen["body"]
    assert "280" in json.loads(seen["body"])["contents"][0]["parts"][0]["text"]


def _timeout(r):
    raise httpx.ReadTimeout("slow")


@pytest.mark.parametrize(
    "handler",
    [
        _timeout,
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"candidates": []}),
        lambda r: _reply("x" * 400 + " #a"),  # over length
        lambda r: _reply("no hashtags here"),
        lambda r: _reply(""),
    ],
)
def test_failures_fall_back(db, gemini, handler):
    out, row = _gen(db, handler)
    assert out.startswith("Spring Sale") and len(out) <= 280
    assert row.status == "fallback" and row.provider == "gemini"
