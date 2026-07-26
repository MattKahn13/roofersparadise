from fastapi.testclient import TestClient
from roofersparadise.app import app

c = TestClient(app)


def test_dates_and_hail():
    d = c.get("/api/dates").json()
    assert "dates" in d
    if d["dates"]:
        one = d["dates"][0]["date"]
        fc = c.get(f"/api/hail?date={one}").json()
        assert fc["type"] == "FeatureCollection"


def test_address_history_shape():
    r = c.get("/api/address_history?lat=27.95&lng=-82.45").json()
    assert "hits" in r and isinstance(r["hits"], list)


def test_ghost_logs():
    assert c.post("/api/ghost", json={"door": "addresses"}).json()["ok"] is True


def test_healthz_ok():
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True
