from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
from app.crypto import load_key

try:
    load_key(settings.token_encryption_key)
except ValueError as e:
    raise SystemExit(f"api refuses to start: {e}") from None

MAX_BODY = 8 * 1024 * 1024

app = FastAPI(title="Social Campaign Publisher")


class BodyLimit:
    """Reject request bodies over MAX_BODY with 413 before any parsing (chunked bodies too)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length", b"0")
        too_big = not declared.isdigit() or int(declared) > MAX_BODY
        messages, size = [], 0
        while not too_big:
            msg = await receive()
            messages.append(msg)
            size += len(msg.get("body", b""))
            too_big = size > MAX_BODY
            if msg["type"] != "http.request" or not msg.get("more_body"):
                break
        if too_big:
            too_large = JSONResponse({"detail": "Request body too large"}, 413)
            return await too_large(scope, receive, send)

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


@app.exception_handler(RequestValidationError)
def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Default handler echoes the input, which breaks on NaN or lone surrogates (-> 500).
    detail = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse({"detail": jsonable_encoder(detail)}, status_code=422)


app.add_middleware(BodyLimit)
app.include_router(router)
Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
