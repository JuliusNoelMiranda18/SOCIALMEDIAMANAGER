import pathlib

import pytest

from app.content.captions import build_prompt, hashtag_count, is_valid, summarize, template_caption
from app.content.fragments import BRAND_VOICE, PLATFORM_RULES

BODY = "We launched a new product today. It is fast and cheap! Come and see. More text."
TITLES = [
    "Spring Sale Launch",
    "😀",
    "a",
    "x" * 200,
    "#tag #tag2 #tag3 #4 #5 #6 #7",
    "Ünïcödé Ñews",
]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("platform", ["x", "instagram"])
def test_template_within_rules(platform, title):
    c = template_caption(platform, title, summarize(BODY), "https://example.com/a")
    assert is_valid(platform, c), c
    lo, hi = PLATFORM_RULES[platform]["hashtags"]
    assert lo <= hashtag_count(c) <= hi


def test_long_url_and_summary():
    c = template_caption("x", "T", summarize("A. " * 500), "https://e.com/" + "a" * 500)
    assert is_valid("x", c)


def test_captions_differ_and_deterministic():
    a = template_caption("x", "Spring Sale", summarize(BODY))
    b = template_caption("instagram", "Spring Sale", summarize(BODY))
    assert a != b
    assert a == template_caption("x", "Spring Sale", summarize(BODY))


def test_summary_two_sentences_and_cap():
    assert summarize(BODY) == "We launched a new product today. It is fast and cheap!"
    assert len(summarize("word " * 500)) <= 300


def test_is_valid_rejects():
    assert not is_valid("x", "")
    assert not is_valid("x", "no tags")
    assert not is_valid("x", "a #b #c #d")
    assert not is_valid("x", "#a " + "z" * 290)


def test_prompt_from_fragments_and_voice_defined_once():
    p = build_prompt("x", "sum")
    assert BRAND_VOICE in p and "280" in p and "sum" in p
    hits = [f.name for f in pathlib.Path("app").rglob("*.py") if BRAND_VOICE[:30] in f.read_text()]
    assert hits == ["fragments.py"]


LONG_WORDS = "a" * 98 + " " + "b" * 99
URLS = [
    None,
    "",
    "https://e.co",
    "https://example.com/" + "x" * 80,
    "https://example.com/page#section",
    "https://example.com/" + "y" * 70 + "#frag#more",
    "https://e.com/" + "z" * 500,
]
EDGE_TITLES = [LONG_WORDS, "c" * 200, "😀 " * 60, " # ", "ab", "Ünïcödé " * 20, "x" * 30 + " y" * 9]


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("title", EDGE_TITLES)
@pytest.mark.parametrize("platform", ["x", "instagram"])
def test_template_rules_hold_for_edge_inputs(platform, title, url):
    c = template_caption(platform, title, summarize("One. " + title + ". Three."), url)
    lo, hi = PLATFORM_RULES[platform]["hashtags"]
    assert len(c) <= PLATFORM_RULES[platform]["max_chars"], len(c)
    assert lo <= hashtag_count(c) <= hi, c


def test_url_fragment_is_stripped():
    c = template_caption("x", "Hello world launch", "s", "https://example.com/page#section")
    assert "#section" not in c and "https://example.com/page" in c
