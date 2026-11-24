from fastapi import FastAPI

app = FastAPI(title="Social Campaign Publisher")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
