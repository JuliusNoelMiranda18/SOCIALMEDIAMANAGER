"""Signed platform callback (ADR-002): verify, dedupe by event_id, apply. Only a verified event
is stored, and only a verified 'delivered' event marks an entry 'published'."""

import hmac
import logging
import re
import time
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt, StrictStr, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.repos import campaigns as entries
from app.repos import webhooks as repo
from app.services.errors import InvalidInput

log = logging.getLogger(__name__)
# No NUL: Postgres text cannot store it (would be a 500).
Text = Annotated[StrictStr, Field(min_length=1, pattern=r"^[^\x00]+$")]


class DeliveryEvent(BaseModel):
    event_id: Annotated[Text, Field(max_length=200)]
    post_id: Text
    status: Literal["delivered", "failed"]
    timestamp: StrictInt


def sign(secret: str, timestamp: str, raw: bytes) -> str:
    """Same scheme as fake_platform/signing.py: hex HMAC-SHA256 over b"<ts>.<raw body>"."""
    return hmac.new(secret.encode(), timestamp.encode() + b"." + raw, sha256).hexdigest()


def verify(
    raw: bytes,
    timestamp: str | None,
    signature: str | None,
    *,
    secret: str,
    now: float,
    tolerance: int,
) -> DeliveryEvent:
    """Pure: raise InvalidInput(reason) unless headers, freshness, signature and body all check."""
    if timestamp is None or signature is None:
        raise InvalidInput("missing signature headers")
    if not re.fullmatch(r"[0-9]{1,12}", timestamp):
        raise InvalidInput("bad timestamp")
    if abs(now - int(timestamp)) > tolerance:
        raise InvalidInput("stale timestamp")
    if not hmac.compare_digest(sign(secret, timestamp, raw).encode(), signature.encode()):
        raise InvalidInput("bad signature")
    try:  # parsed only after the signature checks out
        event = DeliveryEvent.model_validate_json(raw.decode())
    except (UnicodeDecodeError, ValidationError):
        raise InvalidInput("invalid body") from None
    if event.timestamp != int(timestamp):
        raise InvalidInput("timestamp mismatch")
    return event


def handle(session: Session, raw: bytes, timestamp: str | None, signature: str | None) -> str:
    """Returns 'applied', 'unmatched' or 'duplicate'; InvalidInput (no DB write) if unverified."""
    try:
        event = verify(
            raw,
            timestamp,
            signature,
            secret=settings.webhook_secret,
            now=time.time(),
            tolerance=settings.webhook_tolerance_seconds,
        )
    except InvalidInput as e:
        log.warning("webhook rejected: %s", e)  # reason only: never the signature or secret
        raise
    # verify() already decoded it as UTF-8
    if not repo.store(session, event.event_id, raw.decode(), event.post_id, event.status):
        session.rollback()
        return "duplicate"
    changed = entries.apply_delivery(session, event.post_id, event.status)
    session.commit()  # event row and entry update in one transaction
    return "applied" if changed else "unmatched"
