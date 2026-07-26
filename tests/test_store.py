import datetime as dt
from roofersparadise.ingest import store


def test_user_and_subscription_roundtrip(tmp_path):
    db = str(tmp_path / "app.db")
    store.init_db(db)
    store.upsert_user(db, uid="g1", email="a@b.com", name="A")
    store.upsert_user(db, uid="g1", email="a@b.com", name="A2")  # idempotent upsert
    sid = store.add_subscription(db, user_id="g1", zip_="33511", lat=27.9, lng=-82.3, radius_mi=15)
    subs = store.subscriptions_for_user(db, "g1")
    assert len(subs) == 1 and subs[0]["zip"] == "33511"
    assert store.user_email(db, "g1") == "a@b.com"
    assert len(store.active_subscriptions(db)) == 1
    store.delete_subscription(db, sid, "g1")
    assert store.subscriptions_for_user(db, "g1") == []
    assert store.active_subscriptions(db) == []


def test_cooldown_dedup(tmp_path):
    db = str(tmp_path / "app.db")
    store.init_db(db)
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.timezone.utc)
    assert store.recently_alerted(db, "s1", now, hours=3) is False
    store.record_alert(db, sub_id="s1", user_id="g1", storm_ts="t", max_in=1.5, n_cells=4,
                       sent_ok=1, fired_at=now.isoformat())
    assert store.recently_alerted(db, "s1", now, hours=3) is True
    later = now + dt.timedelta(hours=4)
    assert store.recently_alerted(db, "s1", later, hours=3) is False  # cooldown elapsed


def test_alerts_for_user(tmp_path):
    db = str(tmp_path / "app.db")
    store.init_db(db)
    store.record_alert(db, "s1", "g1", "t", 1.5, 4, 1)
    store.record_alert(db, "s2", "g1", "t", 2.0, 9, 1)
    rows = store.alerts_for_user(db, "g1")
    assert len(rows) == 2 and rows[0]["max_in"] in (1.5, 2.0)
