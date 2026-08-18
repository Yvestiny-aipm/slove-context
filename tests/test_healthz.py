"""In-process /healthz and /version. No Docker, no model calls."""

from fastapi.testclient import TestClient
from slove_context.app import app

client = TestClient(app)


def test_healthz_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_ok() -> None:
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("version"), str)
    assert body["version"]
