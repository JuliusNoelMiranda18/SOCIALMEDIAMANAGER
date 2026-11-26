"""Fuzz the caption template: every output must satisfy the platform rules (ISSUE-004).

Runs INSIDE the api container:
    docker compose exec -T api python -I - < scripts/probes/stage2_caption_fuzz.py
"""

import random
import re
import sys

sys.path.insert(0, "/srv")
from app.content.captions import summarize, template_caption  # noqa: E402
from app.content.fragments import PLATFORM_RULES  # noqa: E402

rng = random.Random(20261126)
ATOMS = ["#", "##", "a", "Z", "_", " ", "\n", "🚀", "é", "日本", "#tag", "x" * 40, "1", "-", "%23"]
N = 20_000
bad = []


def rand_text(max_atoms):
    return "".join(rng.choice(ATOMS) for _ in range(rng.randint(0, max_atoms)))


for _ in range(N):
    title = rand_text(60)[:200] or "t"
    body = rand_text(80) or "b"
    url = None
    if rng.random() < 0.7:
        url = "https://e.com/" + rand_text(rng.choice([3, 20, 60]))
    for p, r in PLATFORM_RULES.items():
        cap = template_caption(p, title, summarize(body), url)
        lo, hi = r["hashtags"]
        n = len(re.findall(r"#\w+", cap))
        if not (cap.strip() and len(cap) <= r["max_chars"] and lo <= n <= hi):
            bad.append((p, len(cap), n, title[:40], url and url[:40]))
    caps = {p: template_caption(p, title, summarize(body), url) for p in PLATFORM_RULES}
    if len(set(caps.values())) != len(caps):
        bad.append(("same-caption", title[:40]))

print(f"{'PASS' if not bad else 'FAIL'}  caption fuzz {N} inputs x 2 platforms, bad={len(bad)}")
for b in bad[:10]:
    print("   ", b)
sys.exit(1 if bad else 0)
