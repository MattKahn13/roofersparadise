"""Read one MRMS MESH date into hail cells. Network fetch is isolated in fetch_grib;
cells_from_grid is pure and unit-tested. Read via rasterio (GDAL GRIB driver) -- no eccodes."""
import gzip, os, re, time, datetime as dt
import numpy as np, requests, rasterio

MESH_MIN_MM = 19.0          # 0.75 inch, the marginal-hail floor
ARCHIVE = "https://mtarchive.geol.iastate.edu/{y:04d}/{m:02d}/{d:02d}/mrms/ncep/MESH_Max_1440min/"
_TRIES = 3                  # transient network/listing failures were silently freezing dates as empty


def _get(url, timeout):
    """GET with a few retries -- a transient failure here used to write a permanent empty
    partition (the April-2026 hole). Returns the Response on 200, else None."""
    for i in range(_TRIES):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        if i < _TRIES - 1:
            time.sleep(1.5 * (i + 1))
    return None


def _list(url):
    r = _get(url, 30)
    return re.findall(r'href="((?:MRMS_)?MESH_Max_1440min[^"]+\.grib2\.gz)"', r.text) if r else []


def fetch_grib(day: dt.date, cache_dir: str):
    """Download the last (full-day-max) MESH file for a date; return local .grib2 path or None."""
    url = ARCHIVE.format(y=day.year, m=day.month, d=day.day)
    files = _list(url)
    if not files:
        return None
    r = _get(url + sorted(files)[-1], 90)
    if r is None:
        return None
    try:
        raw = gzip.decompress(r.content)
    except Exception:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{day:%Y%m%d}.grib2")
    open(path, "wb").write(raw)
    return path


def cells_from_grid(arr: np.ndarray, transform):
    """Pure: (lat, lng, mesh_mm) for every cell >= MESH_MIN_MM. transform(col,row)->(lon,lat)."""
    rows, cols = np.where(arr >= MESH_MIN_MM)
    out = []
    for r, c in zip(rows, cols):
        lon, lat = transform(c + 0.5, r + 0.5)
        out.append((round(float(lat), 3), round(float(lon), 3), float(arr[r, c])))
    return out


def read_date(day: dt.date, cache_dir: str, bbox=None):
    """Fetch + read one date. bbox=(w,s,e,n) clips (national if None). Cleans up the grib.
    Returns list of (lat,lng,mm), or None if the date is unavailable."""
    path = fetch_grib(day, cache_dir)
    if not path:
        return None
    try:
        with rasterio.open(path) as ds:
            if bbox:
                from rasterio.windows import from_bounds
                win = from_bounds(*bbox, transform=ds.transform)
                arr = ds.read(1, window=win)
                tr = ds.window_transform(win)
            else:
                arr = ds.read(1)
                tr = ds.transform
        return cells_from_grid(arr, lambda c, r: tr * (c, r))
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
