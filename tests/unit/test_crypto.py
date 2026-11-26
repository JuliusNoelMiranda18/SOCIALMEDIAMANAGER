import os
import subprocess
import sys

import pytest
from cryptography.exceptions import InvalidTag

from app import crypto

KEY = os.urandom(32)


def flip(b: bytes) -> bytes:
    return bytes([b[0] ^ 1]) + b[1:]


def test_round_trip_and_fresh_nonce():
    n1, c1 = crypto.encrypt(KEY, "tok", "x")
    n2, c2 = crypto.encrypt(KEY, "tok", "x")
    assert len(n1) == 12 and n1 != n2 and c1 != c2
    assert crypto.decrypt(KEY, n1, c1, "x") == crypto.decrypt(KEY, n2, c2, "x") == "tok"
    assert b"tok" not in c1


def test_tampering_fails():
    n, c = crypto.encrypt(KEY, "tok", "x")
    for args in [(flip(n), c, "x"), (n, flip(c), "x"), (n, c, "instagram")]:
        with pytest.raises(InvalidTag):
            crypto.decrypt(KEY, *args)
    with pytest.raises(InvalidTag):
        crypto.decrypt(os.urandom(32), n, c, "x")


@pytest.mark.parametrize("bad", ["", "changeme-placeholder", "AAAA", "!!!" * 20])
def test_load_key_rejects(bad):
    with pytest.raises(ValueError, match="make env"):
        crypto.load_key(bad)


def test_api_refuses_to_start_with_bad_key():
    env = {**os.environ, "TOKEN_ENCRYPTION_KEY": "changeme-placeholder"}
    r = subprocess.run(
        [sys.executable, "-c", "import app.main"], env=env, capture_output=True, text=True
    )
    assert r.returncode != 0
    assert "api refuses to start: TOKEN_ENCRYPTION_KEY must be base64 of 32" in r.stderr
