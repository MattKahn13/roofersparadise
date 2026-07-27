"""Daily trailing-window ingest: fetch the last N complete days so a missed day self-heals.
Idempotent -- ingest_date skips partitions already written, and a failed fetch is left undone
(not frozen as empty) so the next day's run retries it.

  python -m roofersparadise.ingest.refresh          # ingest the trailing 3 complete days
"""
from __future__ import annotations
import datetime as dt
from .ingest_hail import run


def trailing_dates(today: dt.date, days: int = 3) -> list[dt.date]:
    """The `days` complete days ending yesterday (today is excluded -- the MRMS daily max is
    only complete after the UTC day ends)."""
    return [today - dt.timedelta(d) for d in range(days, 0, -1)]


def refresh(today: dt.date | None = None, days: int = 3, workers: int = 4) -> None:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    ds = trailing_dates(today, days)
    run(ds[0], ds[-1], workers=workers, run_id=f"refresh-{ds[-1]:%Y%m%d}")
    # rebuild the cumulative grid so the map tiles reflect the new data
    try:
        from .cumulative import build as build_cumulative
    except ImportError:
        from roofersparadise.ingest.cumulative import build as build_cumulative
    build_cumulative()


if __name__ == "__main__":
    refresh()
