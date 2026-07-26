"""Detection + cooldown logic for the real-time hail alert engine."""
import datetime as dt
from roofersparadise.ingest.live_alerts import hail_near, _cooling_down


def test_hail_near_counts_damaging_hail_in_radius():
    cells = [(28.00, -82.40, 30.0),   # near Tampa, 30mm -- counts
             (28.05, -82.42, 40.0),   # near Tampa, 40mm -- counts (and is the max)
             (28.00, -82.40, 10.0),   # near Tampa but < 25mm -- ignored (not damaging)
             (35.00, -97.00, 50.0)]   # Oklahoma -- out of radius
    n, mx = hail_near(cells, 28.0, -82.4, radius_mi=15)
    assert n == 2
    assert mx == round(40.0 / 25.4, 2)


def test_hail_near_empty_when_nothing_in_radius():
    assert hail_near([(35.0, -97.0, 50.0)], 28.0, -82.4, 15) == (0, 0.0)


def test_cooldown_blocks_recent_allows_old():
    now = dt.datetime(2026, 7, 24, 22, 0, 0, tzinfo=dt.timezone.utc)
    assert _cooling_down((now - dt.timedelta(hours=1)).isoformat(), now) is True    # inside 3h window
    assert _cooling_down((now - dt.timedelta(hours=5)).isoformat(), now) is False   # storm long past
    assert _cooling_down(None, now) is False                                        # never alerted


def test_poll_db_fires_once_then_dedupes(tmp_path, monkeypatch):
    """End-to-end poller path: a live hail cell on a watched sub sends one email and records it;
    a second poll within cooldown sends nothing."""
    from roofersparadise.ingest import store, live_alerts
    db = str(tmp_path / "app.db")
    store.init_db(db)
    store.upsert_user(db, "g1", "r@x.com", "R")
    store.add_subscription(db, "g1", "33511", 27.9, -82.3, radius_mi=15)
    monkeypatch.setattr(live_alerts, "fetch_live_hail",
                        lambda: ([(27.9, -82.3, 40.0)], "2026-07-25T18:00:00Z"))
    sent = []
    monkeypatch.setattr(live_alerts, "send_email", lambda to, s, b: (sent.append(to) or True))
    assert live_alerts.poll_db(db) == 1
    assert sent == ["r@x.com"]
    assert live_alerts.poll_db(db) == 0            # cooldown dedupes the second poll


def test_poll_db_no_subs_is_noop(tmp_path):
    from roofersparadise.ingest import live_alerts
    assert live_alerts.poll_db(str(tmp_path / "app.db")) == 0
