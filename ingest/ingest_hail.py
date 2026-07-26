"""Nationwide, date-partitioned, resumable MRMS hail ingestion with provenance.
MRMS files are CONUS-wide, so 'all US' = do not clip. Region is a query filter later.

  python -m roofersparadise.ingest.ingest_hail --start 2026-03-01 --end 2026-03-31 --workers 8

Resumable: a date whose partition file exists is skipped. Idempotent. Empty days are written
as 0-row markers so resume knows they are done."""
import os, argparse, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from .mrms import read_date
from .states import tag_states
from .validate import check_rows

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
HAIL = os.path.join(DATA, "hail")
CACHE = os.path.join(DATA, "_grib_cache")
AUDIT = os.path.join(DATA, "_audit_log.parquet")
COLS = ["lat", "lng", "date", "mesh_mm", "hail_in", "state",
        "_source_file", "_ingested_at", "_pipeline_run_id"]
# Explicit dtypes so EMPTY (no-hail) partitions match populated ones. Without this, an
# empty pandas frame writes null-typed columns and DuckDB fails to unify DOUBLE vs NULL
# across the glob (Conversion Error). Every partition must have the same schema.
SCHEMA = {"lat": "float64", "lng": "float64", "date": "string", "mesh_mm": "float64",
          "hail_in": "float64", "state": "string", "_source_file": "string",
          "_ingested_at": "string", "_pipeline_run_id": "string"}


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def build_rows(cells, day, *, source_file, run_id):
    """Pure: cells [(lat,lng,mm)] -> provenance-tagged dict rows."""
    if not cells:
        return []
    states = tag_states([(lat, lng) for lat, lng, _ in cells])
    ing = _now_iso()
    ds = day.isoformat()
    out = []
    for (lat, lng, mm), st in zip(cells, states):
        out.append({"lat": lat, "lng": lng, "date": ds, "mesh_mm": round(mm, 1),
                    "hail_in": round(mm / 25.4, 2), "state": st,
                    "_source_file": source_file, "_ingested_at": ing, "_pipeline_run_id": run_id})
    return out


def _partition_path(day):
    return os.path.join(HAIL, f"year={day.year}", f"month={day.month:02d}", f"{day.isoformat()}.parquet")


def _log_audit(day, run_id, problems):
    rec = pd.DataFrame([{"date": day.isoformat(), "run_id": run_id,
                         "n_problems": len(problems), "sample": "; ".join(problems[:3]),
                         "logged_at": _now_iso()}])
    if os.path.exists(AUDIT):
        try:
            rec = pd.concat([pd.read_parquet(AUDIT), rec], ignore_index=True)
        except Exception:
            pass   # audit log corrupt/partial -- start fresh; never let a log crash the ingest
    os.makedirs(DATA, exist_ok=True)
    tmp = AUDIT + ".tmp"                # atomic write so a kill mid-write can't corrupt it
    rec.to_parquet(tmp, index=False)
    os.replace(tmp, AUDIT)


def ingest_date(day, run_id):
    dest = _partition_path(day)
    if os.path.exists(dest):
        return -1  # already done (resumable)
    cells = read_date(day, CACHE, bbox=None)  # national
    if cells is None:
        # Fetch FAILED or the date is not yet posted. Do NOT write a 0-row marker -- that would
        # freeze a transient failure forever (skip-by-existence). Leave it undone so a re-run retries.
        return None
    rows = build_rows(cells, day, source_file=f"MESH_Max_1440min/{day:%Y%m%d}", run_id=run_id)
    problems = check_rows(rows)
    if problems:
        _log_audit(day, run_id, problems)
        rows = [r for i, r in enumerate(rows) if not any(f"row {i}:" in p for p in problems)]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    df = pd.DataFrame(rows, columns=COLS).astype(SCHEMA)
    tmp = dest + ".tmp"                 # atomic write: never expose a half-written parquet to the reader
    df.to_parquet(tmp, index=False)
    os.replace(tmp, dest)
    return len(rows)   # swaths are contoured on demand per viewport (app.py /api/hail), not pre-built


def run(start, end, workers, run_id):
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    print(f"ingest {len(days)} days {start}..{end} | run {run_id}", flush=True)
    done = hits = failed = 0
    failed_days = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(ingest_date, d, run_id): d for d in days}
        for f in as_completed(futs):
            done += 1
            n = f.result()
            if n is None:            # fetch failed / not posted -- NOT written, will retry next run
                failed += 1
                failed_days.append(futs[f].isoformat())
            elif n > 0:
                hits += 1
            if done % 50 == 0:
                print(f"  [{done}/{len(days)}] date-partitions with hail: {hits} | failed: {failed}", flush=True)
    msg = f"done: {done} dates, {hits} with hail"
    if failed:
        msg += f" | FAILED (not written, will retry): {failed} -> {sorted(failed_days)[:10]}"
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--run-id", default="")
    a = ap.parse_args()
    rid = a.run_id or f"run-{a.start}-{a.end}"
    run(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), a.workers, rid)


if __name__ == "__main__":
    main()
