"""Phase 0 verification: the app boots and /health reports DB connectivity."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=True)


def test_root_ok():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["service"] == "media-companion-api"


def test_health_reports_database_connected():
    resp = client.get("/health")
    # Requires a reachable database (local Postgres or DATABASE_URL target).
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
