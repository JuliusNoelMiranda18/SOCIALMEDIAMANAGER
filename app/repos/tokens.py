from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import PlatformToken


def get(session: Session, platform: str) -> PlatformToken | None:
    return session.scalars(select(PlatformToken).where(PlatformToken.platform == platform)).first()


def upsert(session: Session, platform: str, nonce: bytes, ciphertext: bytes) -> None:
    q = insert(PlatformToken).values(platform=platform, nonce=nonce, ciphertext=ciphertext)
    q = q.on_conflict_do_update(
        index_elements=["platform"], set_={"nonce": nonce, "ciphertext": ciphertext}
    )
    session.execute(q)
