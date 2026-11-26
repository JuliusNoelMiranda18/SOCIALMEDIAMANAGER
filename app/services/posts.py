import base64
import binascii
import io

from PIL import Image
from sqlalchemy.orm import Session

from app.models import Post
from app.repos import posts as repo
from app.services.errors import InvalidInput

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _check_image(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidInput("image_b64 is not valid base64") from e
    if len(raw) > MAX_IMAGE_BYTES:
        raise InvalidInput("image is larger than 5 MB")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in ("PNG", "JPEG"):
                raise InvalidInput("image must be PNG or JPEG")
            if img.width * img.height > MAX_PIXELS:
                raise InvalidInput("image is larger than 25 megapixels")
            img.load()  # catches truncated or corrupt data
    except InvalidInput:
        raise
    except Exception as e:  # Pillow raises many types, incl. DecompressionBombError
        raise InvalidInput("image_b64 is not a readable image") from e
    return raw


def create_post(
    session: Session, title: str, body: str, source_url: str | None, image_b64: str | None
) -> Post:
    image = _check_image(image_b64) if image_b64 else None
    post = repo.add(session, title=title, body=body, source_url=source_url, source_image=image)
    session.commit()
    return post
