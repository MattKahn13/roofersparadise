"""Real-time hail alerts -- the "be there first" layer, the thing HailTrace actually sells.

Polls the LIVE MRMS MESH_Max_60min feed (max hail in the last hour, updated every ~2 min) and,
for each roofer monitoring a ZIP, fires an alert when fresh >=1-inch hail lands within their
radius. A cooldown means one storm = one ping, not a ping every poll.

Delivery: alerts are appended to alerts.jsonl (a send-ready queue) and surfaced in-app via
/api/alerts. The actual SMS/email SEND is the last-mile integration and is deliberately NOT wired
here -- sending on someone's behalf needs their account + the recipient's opt-in. The queue is
ready for the gmail-selenium sender (email) or an SMS provider to drain.

  python -m roofersparadise.ingest.live_alerts              # one poll
  python -m roofersparadise.ingest.live_alerts --loop 900   # poll every 15 min, forever
"""
import os, re, gzip, json, time, argparse, datetime as dt
import requests, rasterio, numpy as np
from .mrms import cells_from_grid
from . import store
from .email_send import send_email

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR") or os.path.join(HERE, "..", "data")
CACHE = os.path.join(DATA, "_live_cache")
SUBS = os.path.join(DATA, "subscriptions.jsonl")
ALERTS = os.path.join(DATA, "alerts.jsonl")
STATE = os.path.join(DATA, "_alert_state.json")     # per-sub last-alert time (cooldown)
DB = os.environ.get("APP_DB") or os.path.join(DATA, "app.db")
LIVE = "https://mrms.ncep.noaa.gov/data/2D/MESH_Max_60min/"
ALERT_MIN_MM = 25.0     # 1 inch -- damaging; below this we do not wake a roofer
COOLDOWN_H = 3.0        # do not re-alert a sub within this window (one storm, one ping)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def hail_near(cells, lat, lng, radius_mi, min_mm=ALERT_MIN_MM):
    """Pure + testable: (n_cells, max_inches) of hail >= min_mm within radius_mi of (lat,lng)."""
    if not cells:
        return 0, 0.0
    dlat = radius_mi / 69.0
    dlng = radius_mi / (69.0 * max(0.1, abs(np.cos(np.radians(lat)))))
    hits = [mm for (cl, cn, mm) in cells
            if mm >= min_mm and abs(cl - lat) <= dlat and abs(cn - lng) <= dlng]
    return len(hits), (round(max(hits) / 25.4, 2) if hits else 0.0)


def _cooling_down(last_iso, now, hours=COOLDOWN_H):
    if not last_iso:
        return False
    try:
        return (now - dt.datetime.fromisoformat(last_iso.replace("Z", ""))).total_seconds() < hours * 3600
    except Exception:
        return False


def fetch_live_hail():
    """Latest MESH_Max_60min -> (cells[(lat,lng,mm)], file_ts_iso). None on failure."""
    try:
        idx = requests.get(LIVE, timeout=30).text
        files = re.findall(r'((?:MRMS_)?MESH_Max_60min[^"]+\.grib2\.gz)', idx)
        if not files:
            return None
        fn = sorted(files)[-1]
        raw = gzip.decompress(requests.get(LIVE + fn, timeout=90).content)
    except Exception:
        return None
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "live.grib2")
    open(path, "wb").write(raw)
    try:
        with rasterio.open(path) as ds:
            arr = ds.read(1); tr = ds.transform
        cells = cells_from_grid(arr, lambda c, r: tr * (c, r))
    except Exception:
        return None
    finally:
        try: os.remove(path)
        except Exception: pass
    m = re.search(r"(\d{8})-(\d{6})", fn)
    ts = (dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").isoformat() + "Z") if m else _now()
    return cells, ts


def _load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def poll():
    subs = _load_jsonl(SUBS)
    if not subs:
        print("no subscriptions -- nothing to check", flush=True); return 0
    res = fetch_live_hail()
    if not res:
        print("live MRMS fetch failed", flush=True); return 0
    cells, ts = res
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = dt.datetime.now(dt.timezone.utc); fired = 0
    for s in subs:
        sid = s.get("id") or s.get("email") or s.get("phone") or f"{s['lat']},{s['lng']}"
        if _cooling_down(state.get(sid), now):
            continue
        n, mx = hail_near(cells, s["lat"], s["lng"], s.get("radius_mi", 15))
        if n > 0:
            rec = {"ts": ts, "fired_at": _now(), "sub_id": sid, "zip": s.get("zip", ""),
                   "email": s.get("email", ""), "phone": s.get("phone", ""),
                   "lat": s["lat"], "lng": s["lng"], "max_in": mx, "n_cells": n,
                   "msg": f"Hail up to {mx}\" just hit {s.get('zip') or 'your area'} -- get there first."}
            open(ALERTS, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
            state[sid] = _now(); fired += 1
            print(f"ALERT {sid}: {mx}\" hail, {n} cells", flush=True)
    tmp = STATE + ".tmp"; json.dump(state, open(tmp, "w")); os.replace(tmp, STATE)
    print(f"poll @ {ts}: {len(cells)} live hail cells nationwide | {len(subs)} subs | {fired} alerts", flush=True)
    return fired


def poll_db(db=None):
    """Live poll against DB subscriptions (the account-backed path): send an email via Resend
    when fresh damaging hail lands near a watched location, deduped by a per-sub cooldown.
    Records every fire in alerts_sent (which also powers /api/my_alerts and the cooldown)."""
    db = db or DB
    store.init_db(db)
    subs = store.active_subscriptions(db)
    if not subs:
        print("no subs -- nothing to check", flush=True)
        return 0
    res = fetch_live_hail()
    if not res:
        print("live MRMS fetch failed", flush=True)
        return 0
    cells, ts = res
    now = dt.datetime.now(dt.timezone.utc)
    base = os.environ.get("PUBLIC_BASE_URL", "")
    fired = 0
    for s in subs:
        if store.recently_alerted(db, s["id"], now, COOLDOWN_H):
            continue
        n, mx = hail_near(cells, s["lat"], s["lng"], s.get("radius_mi", 15))
        if n <= 0:
            continue
        to = store.user_email(db, s["user_id"]) or ""
        zip_ = s.get("zip") or "your area"
        subj = f"Hail alert: up to {mx}\" just hit {zip_}"
        body = (f"Hail up to {mx} inches was just detected near {zip_} "
                f"({n} radar impact cells within {int(s.get('radius_mi', 15))} mi) in the last hour.\n\n"
                f"This is your window -- get there before the competition does.\n\n"
                f"-- RoofersParadise. Free NOAA MRMS radar."
                + (f" Manage alerts: {base}" if base else ""))
        ok = send_email(to, subj, body) if to else False
        store.record_alert(db, s["id"], s["user_id"], ts, mx, n, 1 if ok else 0)
        fired += 1
        print(f"ALERT sub={s['id']} {mx}\" hail n={n} sent={ok}", flush=True)
    print(f"poll_db @ {ts}: {len(cells)} cells | {len(subs)} subs | {fired} fired", flush=True)
    return fired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="seconds between polls; 0 = one poll")
    a = ap.parse_args()
    if a.loop:
        while True:
            try: poll_db()
            except Exception as e: print("poll error:", str(e)[:120], flush=True)
            time.sleep(a.loop)
    else:
        poll_db()


if __name__ == "__main__":
    main()
