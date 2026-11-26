"""`make env`: create .env from .env.example if missing; fill an invalid TOKEN_ENCRYPTION_KEY.

Never replaces a valid key (that would make stored tokens undecryptable). Runs on host Python 3.9.
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
