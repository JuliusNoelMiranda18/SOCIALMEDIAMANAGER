import time

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.content.captions import build_prompt, is_valid, template_caption
from app.models import LlmCall

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _call_gemini(prompt: str, transport: httpx.BaseTransport | None) -> tuple[str, int, int]:
    with httpx.Client(timeout=settings.llm_timeout_seconds, transport=transport) as client:
        r = client.post(
            _URL.format(model=settings.gemini_model),
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
    r.raise_for_status()
    data = r.json()
    usage = data.get("usageMetadata", {})
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return (
        text.strip(),
        int(usage.get("promptTokenCount", 0)),
        int(usage.get("candidatesTokenCount", 0)),
    )


def generate_caption(
    platform: str,
    summary: str,
    entry_id: int | None,
    session: Session,
    *,
    title: str = "",
    url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Caption for one platform. Always adds exactly one llm_calls row (not committed here).

    status "ok": the model text was used. status "fallback": the template was used, because
    provider is "none" or the model call failed or its reply broke the platform rules.
    """
    gemini = settings.llm_provider == "gemini"
    text, p_tok, c_tok, status = None, 0, 0, "fallback"
    start = time.monotonic()
    if gemini:
        try:
            text, p_tok, c_tok = _call_gemini(build_prompt(platform, summary), transport)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            text = None  # timeout, HTTP error or malformed JSON
        if text is not None and is_valid(platform, text):
            status = "ok"
        else:
            text = None
    latency_ms = int((time.monotonic() - start) * 1000)
    if text is None:
        text = template_caption(platform, title, summary, url)
    cost = (
        p_tok * settings.price_micro_usd_per_million_input
        + c_tok * settings.price_micro_usd_per_million_output
    ) // 1_000_000
    session.add(
        LlmCall(
            entry_id=entry_id,
            provider="gemini" if gemini else "template",
            model=settings.gemini_model if gemini else "template",
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_micro_usd=cost,
            latency_ms=latency_ms,
            status=status,
        )
    )
    return text
