"""Precompute the cumulative hail grid so map tiles are FAST.

A cumulative "all hail" tile would otherwise full-scan every date partition per tile. Instead we
roll the whole archive up ONCE into one small table keyed by cell:
    cumulative(lat, lng, max_in, hits)
      max_in = worst hail ever recorded at that cell (the "Max hail" view)
      hits   = number of distinct storm-days that hit it (the "repeat-hit / hot zones" view)
Tiles then slice this one compact table by bbox (fast) instead of scanning 9.3M rows per tile.

Refreshed by the daily job after new data lands.

  python -m roofersparadise.ingest.cumulative      # rebuild data/cumulative.parquet
"""
from __future__ import annotations
import os
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR") or os.path.join(HERE, "..", "data")
HAIL_GLOB = os.path.join(DATA, "hail", "**", "*.parquet").replace("\\", "/")
OUT = os.path.join(DATA, "cumulative.parquet")


def build(hail_glob: str = HAIL_GLOB, out: str = OUT) -> int:
    con = duckdb.connect()
    tmp = out + ".tmp"
    con.execute(f"""
        COPY (
          SELECT lat, lng,
                 max(hail_in)            AS max_in,
                 count(DISTINCT date)    AS hits
          FROM read_parquet('{hail_glob}')
          WHERE hail_in IS NOT NULL
          GROUP BY lat, lng
        ) TO '{tmp}' (FORMAT PARQUET)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    con.close()
    os.replace(tmp, out)
    print(f"cumulative: wrote {n} cells -> {out}", flush=True)
    return n


if __name__ == "__main__":
    build()
