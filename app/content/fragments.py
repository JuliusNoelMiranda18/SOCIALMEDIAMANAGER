"""Single source of prompt text. Prompts are built from these only (see captions.build_prompt)."""

BRAND_VOICE = (
    "You write social media captions in a warm, clear, confident brand voice. No clickbait."
)

# max_chars and hashtags (min, max) are enforced on every caption, model or template.
PLATFORM_RULES = {
    "x": {
        "max_chars": 280,
        "hashtags": (1, 2),
        "tone": "punchy and direct",
        "format": "one short hook, then a link prompt",
    },
    "instagram": {
        "max_chars": 2200,
        "hashtags": (5, 8),
        "tone": "friendly and visual",
        "format": "a hook, two or three short lines, a call to action, then the hashtags",
    },
}
