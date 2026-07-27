"""Dynamic raster map tiles (256x256 PNG) rendered from the hail data on demand.

Why raster tiles: MapLibre requests them per-viewport-tile, so only what's on screen loads, it
streams in progressively, low zooms are tiny/instant, and zooming shows the coarse parent tile
(blurry) until the sharp child arrives -- exactly the "fast + progressive + blur-in" we want,
without shipping one giant GeoJSON per viewport.

Sources by mode:
  - metric=size / frequency (cumulative "all hail"): slice data/cumulative.parquet (precomputed,
    small -> fast) for max_in / hits per cell.
  - date=YYYY-MM-DD: that single day's cells from the archive.

Colors match the front-end legend (NWS size ramp; purple repeat-hit ramp).
"""
from __future__ import annotations
import io, math, os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR") or os.path.join(HERE, "..", "data")
HAIL_GLOB = os.path.join(DATA, "hail", "**", "*.parquet").replace("\\", "/")
CUM = os.path.join(DATA, "cumulative.parquet").replace("\\", "/")

TILE = 256
CELL_DEG = 0.01            # MRMS MESH grid spacing -- used to size each cell's footprint in px
ALPHA = 184               # ~0.72 opacity, matching the fill layer it replaces

# (threshold, RGB) high->low; first threshold a value clears wins. Matches app.js NWS ramp.
SIZE_BUCKETS = [(2.75, (122, 12, 12)), (2.0, (192, 24, 24)), (1.5, (242, 84, 45)),
                (1.0, (251, 154, 60)), (0.75, (255, 210, 77))]
FREQ_BUCKETS = [(8, (75, 31, 166)), (5, (123, 82, 204)), (3, (169, 143, 224)), (2, (217, 210, 240))]


def tile_bbox(z: int, x: int, y: int):
    """(west, south, east, north) in lng/lat for a slippy tile."""
    n = 2 ** z
    def lng(xt): return xt / n * 360.0 - 180.0
    def lat(yt):
        t = math.pi - 2 * math.pi * yt / n
        return math.degrees(math.atan(math.sinh(t)))
    return lng(x), lat(y + 1), lng(x + 1), lat(y)


def _colorize(grid: np.ndarray, buckets) -> np.ndarray:
    """value grid -> RGBA uint8, bucketed to the legend colors (0 = transparent)."""
    rgba = np.zeros((TILE, TILE, 4), dtype=np.uint8)
    for thr, (r, g, b) in sorted(buckets, key=lambda t: t[0]):   # low->high so higher overwrites
        m = grid >= thr
        rgba[m] = (r, g, b, ALPHA)
    return rgba


def render_tile(con, z: int, x: int, y: int, metric: str = "size", date: str | None = None):
    """PNG bytes for the tile, or None if there is no hail in it (serve as transparent/204)."""
    w, s, e, n = tile_bbox(z, x, y)
    if date:
        col, src, minv, buckets = "hail_in", f"read_parquet('{HAIL_GLOB}')", 0.75, SIZE_BUCKETS
        where = f"date = '{date}' AND hail_in IS NOT NULL"
    elif metric == "frequency":
        col, src, minv, buckets = "hits", f"read_parquet('{CUM}')", 2, FREQ_BUCKETS
        where = "hits IS NOT NULL"
    else:
        col, src, minv, buckets = "max_in", f"read_parquet('{CUM}')", 0.75, SIZE_BUCKETS
        where = "max_in IS NOT NULL"

    # Bin to tile pixels INSIDE DuckDB (Web-Mercator px/py, MAX per pixel) so the query returns
    # <=256x256 rows no matter how many cells fall in the tile -- low-zoom tiles stay fast.
    npow = 2 ** z
    px_e = f"CAST(floor(((lng + 180.0) / 360.0 * {npow} - {x}) * {TILE}) AS INTEGER)"
    py_e = f"CAST(floor(((1.0 - asinh(tan(radians(lat))) / pi()) / 2.0 * {npow} - {y}) * {TILE}) AS INTEGER)"
    q = (f"SELECT {px_e} px, {py_e} py, MAX({col}) v FROM {src} "
         f"WHERE {where} AND lat BETWEEN {s} AND {n} AND lng BETWEEN {w} AND {e} AND {col} >= {minv} "
         f"GROUP BY px, py")
    rows = con.execute(q).fetchall()
    if not rows:
        return None

    a = np.asarray(rows, dtype=np.float64)
    px, py, v = a[:, 0].astype(np.int32), a[:, 1].astype(np.int32), a[:, 2].astype(np.float32)
    keep = (px >= 0) & (px < TILE) & (py >= 0) & (py < TILE)
    px, py, v = px[keep], py[keep], v[keep]
    if not len(v):
        return None

    grid = np.zeros((TILE, TILE), dtype=np.float32)
    np.maximum.at(grid, (py, px), v)

    # Fill each cell's on-screen footprint so cells don't render as sparse 1px dots when zoomed in.
    k = int(round(CELL_DEG / ((e - w) / TILE)))
    if k >= 2:
        k = min(k, 12)
        g = grid.copy()
        for dy in range(k):
            for dx in range(k):
                if dy or dx:
                    g[dy:, dx:] = np.maximum(g[dy:, dx:], grid[:TILE - dy, :TILE - dx])
        grid = g

    img = Image.fromarray(_colorize(grid, buckets), "RGBA")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
