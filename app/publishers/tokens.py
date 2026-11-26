"""Platform access tokens: decrypted from platform_tokens, or fetched via OAuth and stored.

Never log the token or the Authorization header.
"""

import httpx
from cryptography.exceptions import InvalidTag

from app import crypto
from app.config import settings
from app.db import SessionLocal
from app.repos import tokens as repo


class BadTokenResponse(Exception):
    """The token endpoint answered 2xx without a usable access_token."""


def get_token(client: httpx.Client, platform: str, *, refresh: bool = False) -> str:
    key = crypto.load_key(settings.token_encryption_key)
    with SessionLocal() as session:
        row = None if refresh else repo.get(session, platform)
        if row is not None:
            try:
                return crypto.decrypt(key, row.nonce, row.ciphertext, platform)
            except (InvalidTag, ValueError, TypeError):
                pass  # key rotated, row tampered or wrong nonce length: fetch a fresh token
        r = client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.fake_client_id,
                "client_secret": settings.fake_client_secret,
            },
        )
        r.raise_for_status()
        try:
            token = r.json()["access_token"]
        except (ValueError, KeyError, TypeError):
            token = None
        if not isinstance(token, str) or not token:
            raise BadTokenResponse
        repo.upsert(session, platform, *crypto.encrypt(key, token, platform))
        session.commit()
        return token
