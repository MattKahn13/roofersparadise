from fastapi.testclient import TestClient
from roofersparadise.app import app


def _client():
    return TestClient(app)   # fresh client per test -> isolated cookie jar


def test_me_anonymous_is_null():
    r = _client().get("/api/me")
    assert r.status_code == 200 and r.json()["user"] is None


def test_subscribe_requires_auth():
    r = _client().post("/api/subscribe", json={"zip": "33511", "lat": 27.9, "lng": -82.3})
    assert r.status_code == 401


def test_my_endpoints_empty_when_anonymous():
    c = _client()
    assert c.get("/api/my_subscriptions").json()["subscriptions"] == []
    assert c.get("/api/my_alerts").json()["alerts"] == []


def test_dev_login_disabled_by_default():
    assert _client().get("/auth/dev_login").status_code == 404


def test_dev_login_then_subscribe_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "1")
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    c = _client()
    r = c.get("/auth/dev_login", params={"uid": "g1", "email": "r@x.com", "name": "R"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert c.get("/api/me").json()["user"]["email"] == "r@x.com"
    r = c.post("/api/subscribe", json={"zip": "33511", "lat": 27.9, "lng": -82.3})
    assert r.status_code == 200 and r.json()["ok"] is True
    subs = c.get("/api/my_subscriptions").json()["subscriptions"]
    assert len(subs) == 1 and subs[0]["zip"] == "33511"
    # delete round-trips
    sid = subs[0]["id"]
    assert c.request("DELETE", f"/api/subscribe/{sid}").json()["ok"] is True
    assert c.get("/api/my_subscriptions").json()["subscriptions"] == []
