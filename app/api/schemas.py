from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

PgId = Annotated[int, Field(ge=1, le=2**63 - 1)]  # BIGINT range; larger ids would be a DB error


def _db_safe(s: str) -> str:
    s.encode("utf-8")  # lone surrogates from JSON escapes would fail at the DB
    if "\x00" in s:
        raise ValueError("NUL characters are not allowed")
    return s


def _text(**kw):
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, **kw), AfterValidator(_db_safe)
    ]


class PostIn(BaseModel):
    title: _text(max_length=200)
    body: _text(max_length=20000)
    source_url: _text(max_length=2048, pattern=r"^https?://") | None = None
    image_b64: Annotated[str, Field(max_length=7_000_000)] | None = None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    created_at: datetime


class CampaignIn(BaseModel):
    post_id: PgId
    platforms: list[Literal["instagram", "x"]] = Field(min_length=1)
    brand_name: _text(max_length=60) | None = None

    @field_validator("platforms")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate platform")
        return v


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: str
    caption: str
    image_url: str
    image_width: int
    image_height: int
    status: str
    attempts: int
    last_error: str | None
    platform_post_id: str | None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    brand_name: str | None
    created_at: datetime
    entries: list[EntryOut]
