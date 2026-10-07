from fastapi.testclient import TestClient

from app.main import HOST, app


def test_health_returns_ok():
    response = TestClient(app, base_url="http://127.0.0.1").get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_server_binds_to_loopback_only():
    assert HOST == "127.0.0.1"
