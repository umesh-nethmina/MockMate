from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_unknown_route_uses_error_format():
    res = client.get("/does-not-exist")
    assert res.status_code == 404
    assert "error" in res.json()
