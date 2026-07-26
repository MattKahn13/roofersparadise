# RoofersParadise -- How It All Works

The one map of the whole system. Every data layer, where it comes from, how it is transformed, and what
every column means. If something on the map has a number, it is traceable from here. No black boxes.

## Sources (all free)

- **Hail:** NOAA MRMS MESH (Maximum Estimated Size of Hail), pulled from the Iowa State archive
  (`mtarchive.geol.iastate.edu`). MRMS files are CONUS-wide radar-derived hail-size grids; we ingest the
  whole nation per date and filter to a region in the UI.
- **State boundaries:** US Census cartographic state polygons (`data/us_states.geojson`), used only to tag
  each hail cell with its state for region queries.
- **Parcels / permits:** existing `fence-outreach/dataset/` outputs. [wired in Task 11]

## Pipeline

```
MRMS MESH (per date, CONUS)
  -> ingest_hail.py   (threshold >= 0.75in, tag state, provenance columns) -> data/hail/year=/month=/DATE.parquet
  -> validate.py      (range/coords assertions; failures -> data/_audit_log.parquet)
  -> contour.py       (rasterize -> NWS isobands -> Chaikin smooth) -> data/swaths/DATE.geojson
  -> app.py (FastAPI + DuckDB) -> MapLibre UI
```

## Column dictionary (`data/hail/**/*.parquet`)

One row per hail-struck ~0.01deg cell per date. Partitioned `year=YYYY/month=MM/DATE.parquet`.

| Column | Meaning |
|---|---|
| `lat`, `lng` | cell center (WGS84) |
| `date` | storm date (YYYY-MM-DD), the MESH daily-max |
| `mesh_mm` | max estimated hail size, millimeters (raw MRMS) |
| `hail_in` | `mesh_mm / 25.4`, inches (what the UI shows) |
| `state` | US state via point-in-polygon (`us_states.geojson`); null outside US |
| `_source_file` | which MRMS product/date the row came from |
| `_ingested_at` | UTC timestamp of ingestion |
| `_pipeline_run_id` | ingestion run identifier (traceability) |

Threshold: only cells `>= 19mm` (0.75 in, marginal hail) are stored. Empty days are written as 0-row
markers so the resumable ingester knows they are done. Validation failures (impossible hail size, bad
coords) are dropped and logged to `data/_audit_log.parquet` -- never silently kept.

## Free vs paid boundary

**Free (everything in this pipeline above):** the hail map, storm-date selector, total-impact view, and
the address hail-history lookup. All served from `data/hail/` + `data/swaths/`. No login, no gate.

**Paid (ghost-doored -- logged in `ghost_clicks.jsonl`, not yet built as UI):** the homes in a drawn hail
zone, run through the **eliminative filter** (`ingest/premium.py`): given a zone, return its homes MINUS
the ones already re-roofed (a re-roof permit on record, or a satellite-detected reset). We never claim
"this roof is dying"; we only remove the ones a roofer would waste a knock or a stamp on. Then identity +
done-for-you mail. Source: `fence-outreach/dataset/out/leads_enriched.parquet`.

The line is deliberate: free = *where the hail hit* (the targeting HailTrace gates and IHM charges
$999+/yr for); paid = *who to contact, filtered so you don't pay to reach a fresh roof* (the unique edge).

## How to verify anything yourself

Run the ready DuckDB checks in `queries.sql` (added Task 12). Every on-screen number resolves to a row in
`data/hail/` (with its `_source_file` and `_ingested_at`) or a polygon in `data/swaths/`.
