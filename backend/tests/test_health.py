def test_health_ok(anon, fake_sandbox):
    res = anon.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["coding_available"] is True
    fake_sandbox.up = False
    assert anon.get("/health").json()["coding_available"] is False


def test_unknown_route_uses_error_format(anon):
    res = anon.get("/does-not-exist")
    assert res.status_code == 404
    assert "error" in res.json()
