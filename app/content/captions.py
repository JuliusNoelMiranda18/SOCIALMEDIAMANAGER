import re

from app.content.fragments import BRAND_VOICE, PLATFORM_RULES

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_FILLER_TAGS = ["#news", "#update", "#community", "#brand", "#story", "#today", "#new", "#share"]


def summarize(body: str) -> str:
    """Deterministic extractive summary: first two sentences, ~300 chars."""
    text = " ".join(" ".join(_SENTENCE.split(" ".join(body.split()))[:2]).split())
    return text if len(text) <= 300 else text[:299].rstrip() + "…"


def build_prompt(platform: str, summary: str) -> str:
    r = PLATFORM_RULES[platform]
    lo, hi = r["hashtags"]
    return (
        f"{BRAND_VOICE}\n"
        f"Platform: {platform}. Tone: {r['tone']}. Format: {r['format']}.\n"
        f"Maximum {r['max_chars']} characters, {lo} to {hi} hashtags.\n"
        f"Write the caption only.\n\nContent: {summary}"
    )


def hashtag_count(text: str) -> int:
    return len(re.findall(r"#\w+", text))


def is_valid(platform: str, text: str) -> bool:
    r = PLATFORM_RULES[platform]
    lo, hi = r["hashtags"]
    return bool(text.strip()) and len(text) <= r["max_chars"] and lo <= hashtag_count(text) <= hi


def _hashtags(title: str, n: int) -> list[str]:
    # Words over 30 chars are skipped so two tags never crowd out the hook on X.
    words = dict.fromkeys(w.lower() for w in re.findall(r"[^\W_]{3,}", title) if len(w) <= 30)
    tags = [f"#{w}" for w in words] + _FILLER_TAGS
    return list(dict.fromkeys(tags))[:n]


def _clip(text: str, n: int) -> str:
    n = max(n, 1)
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def template_caption(platform: str, title: str, summary: str, url: str | None = None) -> str:
    """Deterministic fallback. Always satisfies is_valid."""
    title, summary = title.replace("#", " "), summary.replace("#", " ")  # '#' would add hashtags
    url = (url or "").split("#")[0]  # a #fragment would count as a hashtag
    text = _template(platform, title, summary, url)
    if is_valid(platform, text):
        return text
    # Guard: should be unreachable, but never return a caption that breaks the rules.
    lo = PLATFORM_RULES[platform]["hashtags"][0]
    return f"{_clip(title, 200)}\n{' '.join(_FILLER_TAGS[:lo])}"


def _template(platform: str, title: str, summary: str, url: str) -> str:
    if platform == "x":
        tags = " ".join(_hashtags(title, 2))
        link = f"Read more: {url}" if url and len(url) <= 100 else "Read more"
        hook = _clip(title, PLATFORM_RULES["x"]["max_chars"] - len(link) - len(tags) - 2)
        return f"{hook}\n{link}\n{tags}"
    lines = [s for s in _SENTENCE.split(summary) if s][:3]
    parts = [
        _clip(title, 200),
        "",
        *(_clip(s, 200) for s in lines),
        "",
        "Tap the link in bio to read more.",
        "",
        " ".join(_hashtags(title, 8)),
    ]
    return "\n".join(parts)
