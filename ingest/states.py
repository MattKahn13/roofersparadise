"""Vectorized point-in-state tagging via the bundled Census GeoJSON. Used only to tag
each hail cell with its state so region queries (Florida, etc.) are precise."""
import os, functools
import geopandas as gpd
from shapely.geometry import Point

_HERE = os.path.dirname(os.path.abspath(__file__))
_GJ = os.path.join(_HERE, "..", "data", "us_states.geojson")


@functools.lru_cache(maxsize=1)
def _states():
    g = gpd.read_file(_GJ)
    name_col = "name" if "name" in g.columns else ("NAME" if "NAME" in g.columns else g.columns[0])
    g = g[[name_col, "geometry"]].rename(columns={name_col: "state"})
    return g.set_crs("EPSG:4326", allow_override=True)


def tag_states(pts):
    """pts = [(lat,lng),...] -> ['Florida', None, ...] aligned to input order."""
    if not pts:
        return []
    gdf = gpd.GeoDataFrame(geometry=[Point(lng, lat) for lat, lng in pts], crs="EPSG:4326")
    j = gpd.sjoin(gdf, _states(), how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")].sort_index()
    return [s if isinstance(s, str) else None for s in j["state"].tolist()]
