"""Background tasks: the live alert poller (every ~10 min) and the daily data refresh.
Gated by ENABLE_WORKERS so the test suite never spawns them. Blocking work (network + rasterio)
runs in a threadpool so it never blocks the event loop."""
from __future__ import annotations
import os
import asyncio
import datetime as dt

try:                                    # top-level when uvicorn runs from roofersparadise/
    from ingest.live_alerts import poll_db
    from ingest.refresh import refresh
except ImportError:                     # package-qualified when imported as roofersparadise.scheduler
    from roofersparadise.ingest.live_alerts import poll_db
    from roofersparadise.ingest.refresh import refresh

POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "600"))
REFRESH_HOUR_UTC = int(os.environ.get("REFRESH_HOUR_UTC", "6"))


async def _poller(interval_s=POLL_INTERVAL_S):
    while True:
        try:
            await asyncio.to_thread(poll_db)
        except Exception as e:
            print("poller error:", str(e)[:160], flush=True)
        await asyncio.sleep(interval_s)


async def _daily_refresh(hour_utc=REFRESH_HOUR_UTC):
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        nxt = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            await asyncio.to_thread(refresh)
        except Exception as e:
            print("refresh error:", str(e)[:160], flush=True)


def start(app):
    """Register startup tasks -- only when ENABLE_WORKERS=1 (prod/local-full, never tests)."""
    if os.environ.get("ENABLE_WORKERS") != "1":
        return

    @app.on_event("startup")
    async def _launch():   # pragma: no cover - background wiring
        asyncio.create_task(_poller())
        asyncio.create_task(_daily_refresh())
        print("scheduler: poller + daily refresh started", flush=True)
