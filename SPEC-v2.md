# RoofersParadise Hail Map -- v2 Spec

> 2026-07-23. Supersedes the v1 local MVP (`roofersparadise/app.py` + Leaflet). Grounded in two research
> passes this session: a competitor analysis (HailTrace, Interactive Hail Maps/HailRecon, SalesRabbit) and
> a UI/library study (map engines, mobile map UX, weather rendering, component kits, reference apps,
> transparent-pipeline tooling). Every library choice below traces to that research; every data choice
> traces to free NOAA MRMS. Build target: still **local first** (no deploy, no domain) until it earns it.

## Goal

Be the free version of HailTrace's targeting layer, built on free NOAA MRMS radar hail data, with a
mobile-first UI that feels better than HailTrace (which is dated), and a pipeline that is fully legible to
the operator -- no black boxes. Free map is the magnet; identity + mail is the (ghost-doored) premium.

## Guiding principles

1. **Transparency-first (the operator can read the whole system).** No black boxes. Every data layer
   carries its source and date; every number on screen traces to a real input; one written map explains
   the entire pipeline. This is a first-class requirement, not a nice-to-have. (Your locked choice:
   legible pipeline + docs, not a separate admin dashboard.)
2. **Free data only.** MRMS MESH (radar hail), public parcels, public permits, NOAA. No paid data.
3. **Honest positioning.** We are "automated radar, like Interactive Hail Maps, but free and unlimited."
   Never "better than HailTrace" (their meteorologist QA is a real edge we do not claim to match).
4. **Legible and lean over polished-but-heavy.** Prefer a stack the operator can hold in his head.
5. **Ghost-door the premium.** Measure willingness-to-pay before building the paid tier.

## The offering (legible economics -- what is free, what is paid, and why)

| Layer | Free | Premium (ghost-doored now) |
|---|---|---|
| Hail map (all sizes, all history) | yes | -- |
| Storm-date + range selector, total-impact view | yes | -- |
| Address -> full hail history ("when was my house hit") | yes | -- |
| ZIP/address alerts on new hail | yes | -- |
| Draw a zone -> list of addresses in it | -- | yes |
| Eliminative permit filter (drop already-re-roofed homes) | -- | **yes (our unique edge)** |
| Homeowner identity (name, tenure, home value) | -- | yes |
| Phone numbers | -- | flagged add-on (TCPA-aware), never default |
| Done-for-you mail campaign (design/print/mail + QR tracking) | -- | yes |
| Asset monitoring (alert when a storm hits a saved client) | -- | yes |

Rationale, in one line each: the free layer is the *targeting* (where the hail hit) that HailTrace gates
and IHM charges $999+/yr for; the paid layer is the *activation* (who to contact, mailed for you) that all
competitors charge for -- and the eliminative permit filter makes our activation provably cheaper per
closed job than theirs, because we do not mail homes that already have a new roof.

## Architecture overview

```
NOAA MRMS MESH (free)                          public parcels + permits (free)
        |                                                   |
   ingest_hail.py  (per-date, provenance-tagged)     (existing dataset/*)
        |                                                   |
   hail per-date store (Parquet, queried via DuckDB)   parcels/permits store
        |                                                   |
   contour -> smooth -> vector tiles (PMTiles)         eliminative filter + identity (premium)
        |                                                   |
        +---------------------  FastAPI backend  -----------+
                                    |
                    MapLibre GL JS + Tailwind + thin JS (mobile-first "spatial cockpit")
                                    |
                    ghost_clicks.jsonl (willingness-to-pay)   PIPELINE.md (the "how it works" map)
```

Everything above the FastAPI line is data the operator can open and read: Parquet files he can query with
DuckDB, PMTiles he can inspect, provenance columns on every row, and one Markdown map of the whole thing.

## Data pipeline (v2)

The v1 ingestion collapses all hail into one accumulated layer. v2 keeps hail **per-date** so the map can
filter by date, show a range, and answer "when was this address hit."

1. **Ingest (rework `mrms_hail.py` -> `ingest_hail.py`), nationwide + modular + overnight-runnable.** MRMS
   files are already CONUS-wide, so "all US" means simply **not clipping** -- extract every hail cell in the
   nation per date. Region (Florida, Tampa, anywhere) becomes a *query filter* on the national store, not a
   separate ingest. For each date, pull MESH_Max_1440min from the Iowa State MRMS archive, threshold at NWS
   categories, and emit one row per hit cell per day: `lat, lng, date, mesh_mm, hail_in, state, _source_file,
   _ingested_at, _pipeline_run_id`. Store as **date-partitioned Parquet** (`hail/year=YYYY/month=MM/*.parquet`).
   Provenance columns mandatory on every row.
   - **Modular + resumable + overnight.** The ingester takes a date range and chunk size, is idempotent
     (skips date-partitions already written, verified by a per-date done-marker), parallelized, and logs
     progress so it can be killed and resumed. A thin `run_overnight.py` wrapper walks the archive in
     month chunks; run it and leave it. **Depth (VERIFIED 2026-07-23): the Iowa State MRMS archive has
     complete MESH_Max_1440min data (96 files/day) only from 2023-01-01 onward -- ~2.5 years, NOT the
     ~11 the earlier draft assumed.** 2020-2022 are sparse/empty with a different filename convention;
     2019 and earlier are absent. So we do NOT match HailTrace's "10+ years" from this free source; we
     have ~2.5 years and we say so. Deeper history would need a different archive (GridRad/NCEI
     reanalysis) -- a separate investigation, not claimed now.
   - **Storage scale.** ~2.5 years x national hail is a few million rows; trivial for Parquet + DuckDB.
     Florida-first only means Florida is what the UI surfaces first; the data underneath is national.
2. **Validate (gatekeeper).** Assert value ranges (0.5-6 in), non-empty on known storm days, coordinates
   inside the bbox. Failures log to an `_audit_log` table, never silently pass. (Research: data assertions
   as gatekeepers.)
3. **Contour to swaths.** Convert the per-date grid to filled isobands at NWS thresholds
   (>=0.75 / 1.0 / 1.75 / 2.5 in) via `rasterio`/GDAL contour or `turf.isoBands`. Smooth the jagged grid
   edges with Chaikin corner-cutting so swaths look organic, not blocky. (Research: the pixels-to-swaths
   recipe.)
4. **Vector tiles.** Tile the smoothed polygons with Tippecanoe into PMTiles (single-file, servable from
   disk/S3, no tile server). Client filters by size/date/opacity instantly, no server round-trip.
5. **Accumulate view.** The "total impact / repeat-hit" layer is a query over the per-date store, not a
   separate ingest -- derive it, don't duplicate it.

DuckDB is the query engine over the Parquet (single-file, reproducible, the operator can run one SQL line
to see any slice). No cloud warehouse.

## The UI (the "spatial cockpit" -- mobile-first, better than HailTrace)

Edge-to-edge MapLibre map with floating, glassmorphic controls. Layout (research-grounded):

- **Top:** a floating search pill (glassmorphic, `backdrop-blur`), 12-16px below the safe-area inset.
  Auto-minimizes on map drag. Search = address geocode -> drops a pin -> hail history.
- **Right utility stack:** translucent rounded pills in the thumb zone -- Layers, Geolocation. Layers pill
  badges the active filter count.
- **Bottom sheet (non-modal, 3 detents: peek ~15% / half ~50% / expanded ~90%).** Velocity-based snapping,
  nested-scroll handoff, no scrim at peek/half so the map stays live behind it. Holds: selected-cell hail
  detail, filters (min hail size, date range), and the address hail-history table.
- **Blue-dot geolocation** with the 3-state cycle (off -> follow -> compass/heading) for field reps.
- **Temporal time-slider** docked at the bottom (Windy/RainViewer pattern): play/pause, scrub, speed (1x/2x/5x),
  a clear past-vs-live break. Scrubbing swaps the active date's swaths.
- **Hail swaths** rendered as MapLibre fill + line layers from the PMTiles, NWS color ramp
  (green 0.75" -> yellow 1" -> red 1.75" -> magenta 2.5"+), semi-transparent fills, crisp outlines.
  Tap a swath -> a Windy-style floating badge shows the hail size next to the finger (not under it).
- **Zoom interpolation** (Zoom Earth pattern): broad swath corridors when zoomed out, sharpening to
  parcel-level detail zoomed in.

Free-tier features on this UI: date/range selector, total-impact toggle, address hail-history, ZIP alerts,
geolocation. Premium features appear as ghost doors (draw-zone -> "see addresses/identity/mail", asset
monitoring), each logging clicks as today.

## Tech stack + rationale

| Layer | Choice | Why (from research) |
|---|---|---|
| Map engine | **MapLibre GL JS** (+ maplibre-cog / pmtiles protocol) | Open-source, WebGL 60fps, free tiles, no surprise API bills during viral storm traffic. Beats Leaflet (DOM/SVG, chokes past ~2k features) and Mapbox/Google (paid). |
| Base tiles | Protomaps PMTiles or Stadia/Versatiles free tier | Free, self-hostable, no per-load billing. |
| Swath tiling | Tippecanoe -> PMTiles | Crisp vector zoom, client-side filter, no tile server. |
| UI styling | **Tailwind CSS** (+ a small set of shadcn/Radix patterns if we add React) | Utility CSS, AI-friendly, ideal for floating overlays on a WebGL canvas. |
| Front-end shell | **Thin JS (vanilla or Alpine) on the existing FastAPI** -- NOT a full Next.js/React SPA | See the fork below. |
| Bottom sheet | CSS scroll-snap + touch handlers (vanilla), or `vaul` if we go React | Native-feeling detents without a heavy dependency. |
| Backend | existing **FastAPI** | Already running; serves the app, the hail API, ghost-click logging, and PMTiles. |
| Data engine | **DuckDB** over partitioned Parquet | Single-file, reproducible, one-line SQL to inspect any slice -- legible. |

**The one fork worth your call (my recommendation baked in):** the research recommends a Next.js + React +
shadcn SPA. I am recommending **against** that for v2 and **for** MapLibre + Tailwind + thin JS on the
FastAPI backend, because your two hard constraints are *legibility* and *MVP-first-local*. A React/Next SPA
is more polished-SaaS but heavier to build, heavier to run locally, and genuinely more of a black box to
read. The thin-JS approach gets the vector map, the spatial-cockpit mobile UX, and the real swaths -- the
90% that matters -- while staying a codebase you can read top to bottom. If we later need heavy stateful
interactivity (a full campaign builder), that is the moment to graduate to React, not before. **Flag: this
is the one place I overrode the research to fit your priorities; veto it if you'd rather go full React.**

## Transparency layer (your requirement, made concrete)

Your choice was legible pipeline + docs. Concretely:

1. **Provenance columns on every data row** -- `_source_file`, `_ingested_at`, `_pipeline_run_id`,
   `pipeline_version` (git commit). Nothing exists in a table without its origin and date attached.
2. **`PIPELINE.md` -- the one "how it all works" map.** Plain-English end-to-end: where each layer comes
   from (with the exact NOAA/parcel/permit source), how it is transformed, what every column means, and
   the free-vs-paid boundary. This is the document you open to understand or explain any piece.
3. **Every on-screen number is traceable.** A hail value -> its MRMS cell + date. A lead list -> its
   parcels minus the permit filter. No magic constants; anything derived is documented where it is derived.
4. **DuckDB one-liners** for self-service inspection -- a `queries.sql` of ready checks ("hail days last
   90d", "cells over 2 inch", "coverage by ZIP") so you can verify any claim yourself in seconds.
5. **`_audit_log`** of every pipeline run (rows in, validations passed/failed, duration) -- a readable
   record, not buried logs. (Optional, if you ever want it visual: point Evidence.dev at `_audit_log` for
   a static freshness/coverage page. Not required by your choice; noted only as a cheap upgrade.)

## Build phases (gated)

- **Phase 1 -- data rework + swaths.** Rework ingestion to per-date + provenance; build the contour ->
  smooth -> PMTiles pipeline; render real swaths in MapLibre. Gate: swaths look right and filter by
  date/size client-side. *Why first: it is the visible quality jump and unblocks everything else.*
- **Phase 2 -- the spatial-cockpit UI.** MapLibre + Tailwind shell, floating search, bottom sheet,
  layer/geolocation pills, time slider, tap-to-inspect badge. Gate: feels good on a phone.
- **Phase 3 -- the free hooks.** Address hail-history lookup (the viral tool) + ZIP alerts off the
  real-time MRMS feed. Gate: "type any address, see every hail date" works.
- **Phase 4 -- premium ghost doors + eliminative filter (data side only).** Wire the draw-zone ghost door;
  build the eliminative permit filter as a query (not the paid UI) so it is ready the moment clicks justify.
- **Transparency runs through all phases** -- provenance columns and `PIPELINE.md` are written as we go,
  never bolted on after.

## What we deliberately will NOT build

Meteorologist verification, a 5-star human ranking, ground-truth photo pins, or a full sales CRM/pipeline
(roofers already live in JobNimbus/AccuLynx -- we export to them, we do not replace them). A full
React/Next SPA (unless the React fork above is chosen). A hosted deployment (local-first until it earns it).

## Honesty guardrails

Every hail number is real MRMS -- no fabricated swaths, no invented verification. Positioning is "free,
unlimited, automated radar," never "better than HailTrace." Florida-first for the data-broker/TCPA posture.
Phones are a flagged add-on, never default.

## Resolved decisions (2026-07-23)

1. **Stack: thin JS on FastAPI, greenlit** (MapLibre + Tailwind + vanilla/Alpine, no React SPA). Bar: it
   looks good and works well enough for roofers. Graduate to React only if a later feature demands it.
2. **Depth: the free MRMS archive, VERIFIED as 2023-01-01 -> today (~2.5 years), not the ~11 first
   assumed.** We do NOT match HailTrace's "10+ years" from this source and never claim to; we lead with
   "free and unlimited." Deeper history is a separate archive investigation (GridRad/NCEI), not scoped now.
3. **Coverage: nationwide data, Florida surfaced first.** MRMS is CONUS-wide, so we ingest the nation per
   date and filter to any region in the UI. A modular, resumable, overnight `run_overnight.py` walks the
   full ~11-year archive. Whole-US is a query away once the data is in.
