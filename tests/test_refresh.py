import datetime as dt
from roofersparadise.ingest import refresh


def test_trailing_dates_excludes_today_and_is_ordered():
    today = dt.date(2026, 7, 25)
    ds = refresh.trailing_dates(today, days=3)
    assert ds == [dt.date(2026, 7, 22), dt.date(2026, 7, 23), dt.date(2026, 7, 24)]


def test_trailing_dates_single_day():
    assert refresh.trailing_dates(dt.date(2026, 7, 25), days=1) == [dt.date(2026, 7, 24)]
