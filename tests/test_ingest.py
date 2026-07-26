import datetime as dt
from roofersparadise.ingest.ingest_hail import build_rows
from roofersparadise.ingest.validate import check_rows


def test_build_rows_has_provenance_and_state():
    cells = [(27.95, -82.45, 44.8)]  # Tampa, 44.8mm
    rows = build_rows(cells, dt.date(2026, 3, 5),
                      source_file="MESH_Max_1440min/20260305", run_id="run-1")
    r = rows[0]
    assert r["hail_in"] == round(44.8 / 25.4, 2)
    assert r["date"] == "2026-03-05"
    assert r["state"] == "Florida"
    for col in ("_source_file", "_ingested_at", "_pipeline_run_id"):
        assert r[col]


def test_build_rows_empty():
    assert build_rows([], dt.date(2026, 3, 5), source_file="x", run_id="r") == []


def test_check_rows_flags_out_of_range():
    good = [{"lat": 27.9, "lng": -82.4, "hail_in": 1.5}]
    bad = [{"lat": 27.9, "lng": -82.4, "hail_in": 99.0}]  # impossible
    assert check_rows(good) == []
    assert "hail_in" in check_rows(bad)[0]


def test_empty_and_populated_partitions_query_together(tmp_path):
    """Regression: empty (no-hail) and populated partitions must share a dtype so DuckDB
    can glob them. Without SCHEMA, empty parquet has null-typed hail_in and DuckDB raises
    'Conversion Error: DOUBLE -> NULL', which 500'd /api/dates."""
    import duckdb, pandas as pd
    from roofersparadise.ingest.ingest_hail import SCHEMA, COLS
    pd.DataFrame([], columns=COLS).astype(SCHEMA).to_parquet(tmp_path / "empty.parquet")
    pd.DataFrame([{"lat": 27.9, "lng": -82.4, "date": "2026-03-05", "mesh_mm": 44.8,
                   "hail_in": 1.76, "state": "Florida", "_source_file": "x",
                   "_ingested_at": "t", "_pipeline_run_id": "r"}],
                 columns=COLS).astype(SCHEMA).to_parquet(tmp_path / "pop.parquet")
    r = duckdb.connect().execute(
        f"select max(hail_in) from read_parquet('{tmp_path.as_posix()}/*.parquet') "
        f"where hail_in is not null").fetchone()
    assert round(r[0], 2) == 1.76


def test_ingest_date_failed_fetch_writes_no_marker(tmp_path, monkeypatch):
    """A failed fetch (read_date -> None) must NOT write a partition, so a re-run retries it.
    Regression for the April-2026 hole: transient failures were frozen as empty markers that
    skip-by-existence then made permanent."""
    import os
    from roofersparadise.ingest import ingest_hail as ih
    monkeypatch.setattr(ih, "HAIL", str(tmp_path / "hail"))
    monkeypatch.setattr(ih, "read_date", lambda *a, **k: None)
    r = ih.ingest_date(dt.date(2026, 4, 20), "t")
    assert r is None
    assert not os.path.exists(ih._partition_path(dt.date(2026, 4, 20)))


def test_ingest_date_genuine_empty_writes_marker(tmp_path, monkeypatch):
    """A successful read with no hail (read_date -> []) DOES write a 0-row marker so it is
    not needlessly refetched."""
    import os
    from roofersparadise.ingest import ingest_hail as ih
    monkeypatch.setattr(ih, "HAIL", str(tmp_path / "hail"))
    monkeypatch.setattr(ih, "read_date", lambda *a, **k: [])
    r = ih.ingest_date(dt.date(2026, 1, 15), "t")
    assert r == 0
    assert os.path.exists(ih._partition_path(dt.date(2026, 1, 15)))
