"""RoofersParadise v2 backend. Serves the MapLibre UI, swath GeoJSON, the address
hail-history lookup (DuckDB over the partitioned Parquet), and ghost-door logging.
Every response traces to data/ files -- see PIPELINE.md. No black boxes.

  uvicorn app:app --host 127.0.0.1 --port 8010   (from roofersparadise/)
"""
import os, json, glob, math, datetime, secrets
from pathlib import Path
import duckdb
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
try:                                    # uvicorn runs app.py as a top-level module (cwd=roofersparadise)
    from ingest.contour import build_swaths_cells, FL_BBOX, FREQ_BANDS
    from ingest.tiles import render_tile
    from ingest import store
    from auth import router as auth_router, current_user, _db as _appdb
    import scheduler
except ImportError as _primary_err:     # ...but tests import it as a package
    try:
        from roofersparadise.ingest.contour import build_swaths_cells, FL_BBOX, FREQ_BANDS
        from roofersparadise.ingest.tiles import render_tile
        from roofersparadise.ingest import store
        from roofersparadise.auth import router as auth_router, current_user, _db as _appdb
        from roofersparadise import scheduler
    except ImportError:
        raise _primary_err              # surface the REAL top-level import error, not the package-fallback miss

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR") or os.path.join(HERE, "data")
HAIL_DIR = Path(DATA, "hail").as_posix()
HAIL_GLOB = f"{HAIL_DIR}/**/*.parquet"
SWATHS = os.path.join(DATA, "swaths")
CLICKS = os.path.join(HERE, "ghost_clicks.jsonl")
SUBS = os.path.join(DATA, "subscriptions.jsonl")   # roofers monitoring a ZIP for live hail
ALERTS = os.path.join(DATA, "alerts.jsonl")         # fired alerts (written by ingest/live_alerts.py)
CUM = os.path.join(DATA, "cumulative.parquet").replace("\\", "/")   # precomputed grid for fast tiles

app = FastAPI(title="RoofersParadise v2")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "dev-insecure-secret"))
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


def _has_hail():
    return bool(glob.glob(os.path.join(DATA, "hail", "**", "*.parquet"), recursive=True))


_CON = duckdb.connect()   # persistent -- caches parquet metadata across requests (per-request connect re-read it every time)


def _q(sql):
    """Run a DuckDB query on the shared connection via a per-call cursor (thread-safe reads).
    Returns [] on any read error (e.g. a partition mid-write during a backfill) so the map
    degrades gracefully instead of 500-ing."""
    try:
        return _CON.cursor().execute(sql).fetchall()
    except Exception as e:
        print(f"[api] duckdb read failed, returning empty: {str(e)[:160]}", flush=True)
        return []


def _valid_date(d):
    """Accept only YYYY-MM-DD (these strings go into SQL) -- else drop it."""
    return d if (d and len(d) == 10 and d[4] == "-" and d[7] == "-"
                 and d.replace("-", "").isdigit()) else None


@app.get("/tiles/{z}/{x}/{y}.png")
def tile_png(z: int, x: int, y: int, metric: str = "size",
             date: str | None = None, start: str | None = None, end: str | None = None):
    """Raster hail tile for the map -- MapLibre requests these per viewport-tile so the map loads
    progressively and only what's on screen. start/end = a week window. Empty tile -> 204."""
    date, start, end = _valid_date(date), _valid_date(start), _valid_date(end)
    try:
        png = render_tile(_CON.cursor(), z, x, y, metric=metric, date=date, start=start, end=end)
    except Exception as e:
        print(f"[tile] {z}/{x}/{y} m={metric} d={date} {start}..{end} failed: {str(e)[:160]}", flush=True)
        png = None
    if not png:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/point")
def api_point(lat: float, lng: float):
    """Tapped point -> worst hail + how many times + the actual DATES it was hit (US land only)."""
    box = (f"lat between {lat - 0.03} and {lat + 0.03} and lng between {lng - 0.03} and {lng + 0.03}")
    cum = _q(f"""select max_in, hits from read_parquet('{CUM}') where {box}
                 order by (lat - {lat}) * (lat - {lat}) + (lng - {lng}) * (lng - {lng}) limit 1""")
    dts = _q(f"""select date, max(hail_in) mx from read_parquet('{HAIL_GLOB}')
                 where {box} and state is not null and hail_in >= 0.75
                 group by date order by date desc limit 15""")
    return {
        "max_in": round(float(cum[0][0]), 2) if cum and cum[0][0] is not None else None,
        "hits": int(cum[0][1]) if cum and cum[0][0] is not None else 0,
        "dates": [{"date": r[0], "max_in": round(float(r[1]), 2)} for r in dts],
    }


@app.get("/")
def index():
    # no-store so a reload always re-fetches the page (and thus the version-stamped app.js);
    # otherwise the browser serves a cached UI and code changes never appear.
    return FileResponse(os.path.join(HERE, "static", "index.html"),
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "has_hail": _has_hail()}


@app.get("/api/dates")
def dates():
    # Every national storm day (from the raw cells). On-demand contour means any of these
    # renders for whatever viewport the user is looking at.
    if not _has_hail():
        return {"dates": []}
    rows = _q(f"""select date, count(*) n, max(hail_in) mx
                  from read_parquet('{HAIL_GLOB}') where hail_in is not null
                  group by date having count(*) > 0 order by date""")
    return {"dates": [{"date": r[0], "cells": int(r[1]), "max_in": round(r[2], 2)} for r in rows]}


@app.get("/api/hail")
def hail(date: str = "", start: str = "", end: str = "", bbox: str = "", metric: str = "size"):
    """Hail swaths for the current map VIEWPORT, contoured on demand from the (national) cells.
    bbox='W,S,E,N'. metric='size' = max hail per cell (single date or cumulative worst-hail);
    metric='frequency' = how many storm-days hit each cell (the repeat-hit 'hot zones' view).
    Viewport scoping is what lets this scale to the whole US without shipping the country."""
    if bbox:
        try:
            W, S, E, N = (float(x) for x in bbox.split(","))
        except Exception:
            return JSONResponse({"type": "FeatureCollection", "features": []})
    else:
        W, S, E, N = FL_BBOX
    conds = [f"lng between {W} and {E}", f"lat between {S} and {N}", "hail_in is not null"]
    if date:
        conds.append(f"date = '{date}'")
    if start:
        conds.append(f"date >= '{start}'")
    if end:
        conds.append(f"date <= '{end}'")
    where = " and ".join(conds)
    if metric == "frequency":
        rows = _q(f"""select lat, lng, count(distinct date) hits from read_parquet('{HAIL_GLOB}')
                      where {where} group by lat, lng""")
        df = pd.DataFrame(rows, columns=["lat", "lng", "hits"])
        return JSONResponse(build_swaths_cells(df, (W, S, E, N), value_col="hits",
                                               bands=FREQ_BANDS, prop="hits"))
    rows = _q(f"""select lat, lng, max(hail_in) hail_in from read_parquet('{HAIL_GLOB}')
                  where {where} group by lat, lng""")
    df = pd.DataFrame(rows, columns=["lat", "lng", "hail_in"])
    return JSONResponse(build_swaths_cells(df, (W, S, E, N)))


@app.get("/api/address_history")
def address_history(lat: float, lng: float, radius_mi: float = 0.5):
    """Every hail date within radius of a point -- the 'when was my house hit' tool."""
    if not _has_hail():
        return {"hits": []}
    dlat = radius_mi / 69.0
    dlng = radius_mi / (69.0 * max(0.1, abs(math.cos(math.radians(lat)))))
    rows = _q(f"""select date, max(hail_in) mx from read_parquet('{HAIL_GLOB}')
                  where lat between {lat-dlat} and {lat+dlat}
                    and lng between {lng-dlng} and {lng+dlng}
                  group by date order by date desc""")
    return {"hits": [{"date": r[0], "max_in": round(r[1], 2)} for r in rows]}


@app.post("/api/ghost")
async def ghost(req: Request):
    b = await req.json()
    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "door": b.get("door", ""),
           "email": (b.get("email") or "").strip(), "zone": b.get("zone", "")}
    open(CLICKS, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
    return JSONResponse({"ok": True})


@app.get("/api/ghost_stats")
def ghost_stats():
    if not os.path.exists(CLICKS):
        return {"total": 0, "by_door": {}}
    rows = [json.loads(l) for l in open(CLICKS, encoding="utf-8") if l.strip()]
    by = {}
    for r in rows:
        by[r["door"]] = by.get(r["door"], 0) + 1
    return {"total": len(rows), "by_door": by, "emails": sum(1 for r in rows if r.get("email"))}


@app.get("/api/me")
def me(request: Request):
    return {"user": current_user(request)}


@app.post("/api/subscribe")
async def subscribe(request: Request):
    """Watch a spot (ZIP / current map center) for live hail. Requires sign-in; the poller
    (ingest/live_alerts.poll_db) checks the real-time feed against these and emails on a hit."""
    u = current_user(request)
    if not u:
        return JSONResponse({"ok": False, "error": "sign in first"}, status_code=401)
    b = await request.json()
    lat, lng = b.get("lat"), b.get("lng")
    if lat is None or lng is None:
        return JSONResponse({"ok": False, "error": "need a location"}, status_code=400)
    store.init_db(_appdb())
    sid = store.add_subscription(_appdb(), u["id"], (b.get("zip") or "").strip(),
                                 float(lat), float(lng), float(b.get("radius_mi") or 15))
    return JSONResponse({"ok": True, "id": sid})


@app.get("/api/my_subscriptions")
def my_subscriptions(request: Request):
    u = current_user(request)
    if not u:
        return {"subscriptions": []}
    store.init_db(_appdb())
    return {"subscriptions": store.subscriptions_for_user(_appdb(), u["id"])}


@app.delete("/api/subscribe/{sid}")
def unsubscribe(sid: str, request: Request):
    u = current_user(request)
    if not u:
        return JSONResponse({"ok": False}, status_code=401)
    store.init_db(_appdb())
    store.delete_subscription(_appdb(), sid, u["id"])
    return {"ok": True}


@app.get("/api/my_alerts")
def my_alerts(request: Request):
    u = current_user(request)
    if not u:
        return {"alerts": []}
    store.init_db(_appdb())
    return {"alerts": store.alerts_for_user(_appdb(), u["id"])}


@app.get("/api/alerts")
def alerts(limit: int = 25):
    """Recent fired hail alerts -- powers an in-app feed and proves the pipeline works."""
    if not os.path.exists(ALERTS):
        return {"alerts": []}
    rows = [json.loads(l) for l in open(ALERTS, encoding="utf-8") if l.strip()]
    return {"alerts": rows[-limit:][::-1]}


# Background poller + daily refresh (only when ENABLE_WORKERS=1; never during tests).
scheduler.start(app)
