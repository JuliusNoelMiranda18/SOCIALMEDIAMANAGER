import hmac
from hashlib import sha256


def sign(secret: str, timestamp: int | str, body: str) -> str:
    """Webhook scheme: HMAC-SHA256 hex over "<ts>.<raw body>". Reused by Stage 5."""
    return hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), sha256).hexdigest()
