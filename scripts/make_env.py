"""`make env`: create .env from .env.example if missing; fill an invalid TOKEN_ENCRYPTION_KEY
and an empty or placeholder WEBHOOK_SECRET.

Never replaces a valid value (a new key would make stored tokens undecryptable). Never prints
a value. Runs on host Python 3.9.
"""

import base64
import binascii
import re
import secrets
import shutil
from pathlib import Path

env = Path(".env")
if not env.exists():
    shutil.copy(".env.example", env)
text = env.read_text()
m = re.search(r"^TOKEN_ENCRYPTION_KEY=(.*)$", text, re.M)
try:
    ok = m is not None and len(base64.b64decode(m.group(1).strip(), validate=True)) == 32
except (binascii.Error, ValueError):
    ok = False
if ok:
    print(".env: TOKEN_ENCRYPTION_KEY already set")
else:
    line = "TOKEN_ENCRYPTION_KEY=" + base64.b64encode(secrets.token_bytes(32)).decode()
    if m:
        text = text[: m.start()] + line + text[m.end() :]
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    env.write_text(text)
    print(".env: wrote a fresh TOKEN_ENCRYPTION_KEY")

text = env.read_text()
m = re.search(r"^WEBHOOK_SECRET=(.*)$", text, re.M)
if m and m.group(1).strip() not in ("", "changeme-placeholder"):
    print(".env: WEBHOOK_SECRET already set")
else:
    line = "WEBHOOK_SECRET=" + secrets.token_hex(32)
    if m:
        text = text[: m.start()] + line + text[m.end() :]
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    env.write_text(text)
    print(".env: wrote a fresh WEBHOOK_SECRET (restart api and fake-platform: make up)")
