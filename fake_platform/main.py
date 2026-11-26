import asyncio
import json
import logging
import math
import os
import random
import secrets
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from email.utils import formatdate
from typing import Literal
from urllib.parse import parse_qs

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from fake_platform.signing import sign

log = logging.getLogger("fake_platform")
app = FastAPI(title="Fake Platform")

DEFAULT_WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "http://api:8000/webhook/social-delivery")


@app.exception_handler(RequestValidationError)
async def bad_request(_: Request, exc: RequestValidationError):
    # default handler echoes `input`, which breaks JSON encoding for NaN/Infinity (was a 500)
    errs = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse({"detail": errs}, status_code=422)


class RateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    retry_after_seconds: int = Field(30, ge=0)
    count: int | None = Field(None, ge=1)  # only the next N fresh posts get 429, then auto-off
    format: Literal["seconds", "http-date"] = "seconds"


class DropResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    delay_seconds: int = Field(30, ge=0)


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_limit: RateLimit = RateLimit()
    failure_rate: float = Field(0.0, ge=0, le=1, allow_inf_nan=False)
    drop_response: DropResponse = DropResponse()
    forged_signature: bool = False
    webhook_url: str = DEFAULT_WEBHOOK_URL
    latency_ms: int = Field(0, ge=0, le=10000)


class ControlUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_limit: RateLimit | None = None
    failure_rate: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    drop_response: DropResponse | None = None
    forged_signature: bool | None = None
    webhook_url: str | None = None
    latency_ms: int | None = Field(None, ge=0, le=10000)


class PostIn(BaseModel):
    platform: Literal["instagram", "x"]
    caption: str
    image_url: str | None = None


control = Control()
tokens: set[str] = set()
posts: list[dict] = []
idempotency: dict[str, tuple[int, dict]] = {}  # key -> (status, response body)
stats: list[dict] = []  # every POST /v1/posts: arrival time, key, final status


@app.middleware("http")
async def record_post_requests(request: Request, call_next):
    if request.method != "POST" or request.url.path != "/v1/posts":
        return await call_next(request)
    row = {
        "at": datetime.now(UTC).isoformat(),
        "idempotency_key": request.headers.get("idempotency-key"),
        "status": None,
    }
    stats.append(row)
    response = await call_next(request)
    row["status"] = response.status_code
    return response


def deliver(url: str, body: str, headers: dict[str, str]) -> None:
    """Send one callback. Replaceable: tests monkeypatch this to capture it."""
    req = urllib.request.Request(
        url, body.encode(), {"Content-Type": "application/json", **headers}, method="POST"
    )
    urllib.request.urlopen(req, timeout=5).close()


def send_callback(post: dict) -> None:
    ts = int(time.time())
    body = json.dumps(
        {
            "event_id": str(uuid.uuid4()),
            "post_id": post["id"],
            "status": "delivered",
            "platform": post["platform"],
            "timestamp": ts,
        }
    )
    sig = "0" * 64 if control.forged_signature else sign(settings.webhook_secret, ts, body)
    try:
        deliver(control.webhook_url, body, {"X-Timestamp": str(ts), "X-Signature": sig})
    except Exception as e:  # unreachable until Stage 5; never break the post
        log.warning("callback to %s failed: %s", control.webhook_url, type(e).__name__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/oauth/token")
async def token(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode(errors="replace")).items()}
    if form.get("grant_type") != "client_credentials" or not (
        form.get("client_id") and form.get("client_secret")
    ):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    t = secrets.token_urlsafe(24)
    tokens.add(t)
    return {"access_token": t, "token_type": "Bearer", "expires_in": 3600}


def require_token(authorization: str | None = Header(None)) -> None:
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or value not in tokens:
        raise HTTPException(401, "invalid or missing token")


@app.post("/v1/posts", status_code=201, dependencies=[Depends(require_token)])
async def create_post(
    body: PostIn,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(None),
):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header required")
    if idempotency_key in idempotency:
        status, stored = idempotency[idempotency_key]
        return JSONResponse(stored, status_code=status)
    rl = control.rate_limit
    if rl.enabled:
        if rl.count is not None:
            rl.count -= 1
            if rl.count == 0:
                rl.enabled, rl.count = False, None
        wait = rl.retry_after_seconds
        # Round the date up so a client honouring it never comes back early.
        retry_after = (
            str(wait)
            if rl.format == "seconds"
            else formatdate(math.ceil(time.time()) + wait, usegmt=True)
        )
        return JSONResponse(
            {"error": "rate_limited"}, status_code=429, headers={"Retry-After": retry_after}
        )
    if random.random() < control.failure_rate:
        return JSONResponse({"error": "unavailable"}, status_code=503)
    post = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "idempotency_key": idempotency_key,
        "created_at": datetime.now(UTC).isoformat(),
    }
    posts.append(post)
    response = {"id": post["id"], "platform": post["platform"], "status": "accepted"}
    idempotency[idempotency_key] = (201, response)
    background.add_task(send_callback, post)
    if control.latency_ms:  # after storing: a caller killed now leaves an accepted post behind
        await asyncio.sleep(control.latency_ms / 1000)
    if control.drop_response.enabled:
        await asyncio.sleep(control.drop_response.delay_seconds)
    return response


@app.get("/_posts")
def list_posts() -> list[dict]:
    return posts


@app.get("/_stats")
def get_stats() -> dict:
    return {"post_requests": stats}


@app.get("/_tokens")
def list_tokens() -> list[str]:
    # dev-only: lets probe 6 grep the DB dump and logs for every issued token
    return sorted(tokens)


@app.get("/_control")
def get_control() -> Control:
    return control


@app.post("/_control")
def update_control(update: ControlUpdate) -> Control:
    for k, v in update.model_dump(exclude_none=True, exclude_unset=True).items():
        # nested switches merge: only the fields the client sent change
        setattr(control, k, getattr(control, k).model_copy(update=v) if isinstance(v, dict) else v)
    return control


@app.post("/_control/reset")
def reset() -> Control:
    global control
    control = Control()
    tokens.clear()
    posts.clear()
    idempotency.clear()
    stats.clear()
    return control
