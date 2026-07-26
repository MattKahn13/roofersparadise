"""Overnight nationwide backfill: walk the MRMS archive in month chunks, calling the
resumable ingester per chunk. Idempotent -- survives a kill/restart because ingest_date
skips date-partitions already written.

COVERAGE (verified 2026-07-23): the Iowa State MRMS archive has COMPLETE MESH_Max_1440min
data (96 files/day) only from 2023-01-01 onward. 2020-2022 dirs exist but are sparse/empty
with a different filename convention; 2019 and earlier are absent. So the honest free depth
is ~2.5 years (2023 -> today), NOT the decade HailTrace claims. Do not backfill before 2023
-- it just writes empty partitions.

  nohup python -m roofersparadise.ingest.run_overnight > roofersparadise/data/_overnight.log 2>&1 &
"""
import datetime as dt, calendar, argparse
from .ingest_hail import run


def month_chunks(start, end):
    d = start
    while d <= end:
        last = dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        yield d, min(last, end)
        d = last + dt.timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")  # MRMS MESH archive starts here (see module docstring)
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    for a0, b0 in month_chunks(start, end):
        run(a0, b0, workers=a.workers, run_id=f"overnight-{a0:%Y%m}")


if __name__ == "__main__":
    main()
