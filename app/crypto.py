"""AES-GCM for platform tokens at rest. AAD is the platform name, so a row can't be swapped."""

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def load_key(b64: str) -> bytes:
    try:
        key = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != 32:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY must be base64 of 32 random bytes; run `make env` to create one"
        )
    return key


def encrypt(key: bytes, plaintext: str, aad: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode())


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: str) -> str:
    """Raises InvalidTag on tampering or wrong key/AAD; ValueError on a bad nonce length."""
    return AESGCM(key).decrypt(nonce, ciphertext, aad.encode()).decode()
