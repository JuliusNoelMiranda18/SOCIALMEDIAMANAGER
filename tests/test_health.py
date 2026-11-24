from fastapi.testclient import TestClient

from app.main import app as api_app
from fake_platform.main import app as fake_app


def test_api_health():
    r = TestClient(api_app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_fake_platform_health():
    r = TestClient(fake_app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
