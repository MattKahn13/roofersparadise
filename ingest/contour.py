"""Per-date hail cells -> smoothed GeoJSON swaths at NWS thresholds. Region-scoped
(default Florida bbox) so output stays small enough to serve as GeoJSON directly.

Approach: rasterize the date's cells to a grid, classify each cell into the highest NWS
hail band it clears, vectorize contiguous bands with rasterio.features.shapes (robust,
no matplotlib internals), then Chaikin-smooth the grid-blocky rings into organic swaths."""
import os, json, glob
import numpy as np, pandas as pd
from rasterio.features import shapes
from rasterio.transform import from_origin
from global_land_mask import globe   # drop ocean hail -- no roofs over water

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
BANDS_IN = [0.75, 1.0, 1.75, 2.5]          # marginal / severe / very-large / giant
FL_BBOX = (-87.7, 24.4, -79.8, 31.1)       # default region to surface
GRID = 0.01


def chaikin(ring, iterations=2):
    """Corner-cutting smoothing on a closed ring of (x,y). Keeps the ring closed."""
    pts = ring[:]
    for _ in range(iterations):
        new = [pts[0]]
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            new.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            new.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        new.append(pts[0])
        pts = new
    return pts


def _band_index(hail_in):
    idx = 0
    for i, thr in enumerate(BANDS_IN):
        if hail_in >= thr:
            idx = i + 1
    return idx


def _cells_for_date(date_iso, bbox):
    y, m, _ = date_iso.split("-")
    p = os.path.join(DATA, "hail", f"year={y}", f"month={m}", f"{date_iso}.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    w, s, e, n = bbox
    return df[(df.lng >= w) & (df.lng <= e) & (df.lat >= s) & (df.lat <= n)]


def _adaptive_grid(bbox, max_dim=1400):
    """Grid cell size in degrees. Fine (0.01) when zoomed in; coarser when the bbox is
    large so a zoomed-out / national request keeps the raster (and contour time) bounded."""
    w, s, e, n = bbox
    return max(GRID, round(max(e - w, n - s) / max_dim, 4))


FREQ_BANDS = [2, 3, 5, 8]   # storm-day counts for the "repeat-hit / hot zones" (Honey Hole) view


def build_swaths_cells(df, bbox, value_col="hail_in", bands=None, prop="hail_in"):
    """Contour an in-memory cells frame within bbox into smoothed GeoJSON swaths. Land-masked
    (no ocean) and adaptive-resolution. Generalized: `value_col` is the number binned into
    `bands` (default = max hail size; pass value_col='hits'/FREQ_BANDS for repeat-hit hot zones),
    and each feature carries {prop: band_value}. Shared by the pre-build and the viewport endpoint."""
    bands = bands or BANDS_IN
    feats = []
    if df is None or len(df) == 0:
        return {"type": "FeatureCollection", "features": feats}
    df = df[globe.is_land(df["lat"].to_numpy(), df["lng"].to_numpy())]   # drop ocean cells
    if len(df) == 0:
        return {"type": "FeatureCollection", "features": feats}
    w, s, e, n = bbox
    grid = _adaptive_grid(bbox)
    nx = int(round((e - w) / grid)) + 1
    ny = int(round((n - s) / grid)) + 1
    band = np.zeros((ny, nx), dtype=np.int32)   # row 0 = NORTH (north-up for from_origin)
    lng = df["lng"].to_numpy(); lat = df["lat"].to_numpy(); val = df[value_col].to_numpy()
    gx = np.round((lng - w) / grid).astype(np.int64)
    gy = np.round((n - lat) / grid).astype(np.int64)          # north-up
    bidx = np.searchsorted(np.asarray(bands), val, side="right").astype(np.int32)   # vectorized band index
    keep = (gx >= 0) & (gx < nx) & (gy >= 0) & (gy < ny) & (bidx > 0)
    np.maximum.at(band, (gy[keep], gx[keep]), bidx[keep])     # highest band per grid cell
    transform = from_origin(w, n, grid, grid)
    for geom, v in shapes(band, mask=band > 0, transform=transform):
        pv = bands[int(v) - 1]
        rings = []
        for ring in geom["coordinates"]:
            r = [tuple(pt) for pt in ring]
            if len(r) >= 4:
                rings.append([list(p) for p in chaikin(r, 2)])
        if rings:
            feats.append({"type": "Feature", "properties": {prop: pv},
                          "geometry": {"type": "Polygon", "coordinates": rings}})
    return {"type": "FeatureCollection", "features": feats}


def build_swaths(date_iso, bbox=FL_BBOX):
    return build_swaths_cells(_cells_for_date(date_iso, bbox), bbox)


def write_swaths(date_iso, bbox=FL_BBOX):
    fc = build_swaths(date_iso, bbox)
    os.makedirs(os.path.join(DATA, "swaths"), exist_ok=True)
    dest = os.path.join(DATA, "swaths", f"{date_iso}.geojson")
    json.dump(fc, open(dest, "w"))
    return dest, len(fc["features"])


def build_all(bbox=FL_BBOX):
    for p in sorted(glob.glob(os.path.join(DATA, "hail", "**", "*.parquet"), recursive=True)):
        date_iso = os.path.basename(p)[:-8]
        _, n = write_swaths(date_iso, bbox)
        if n:
            print(f"  {date_iso}: {n} swath polys", flush=True)


if __name__ == "__main__":
    build_all()
