"""Premium (ghost-doored) data side: the ELIMINATIVE filter. Given a hail zone, return the
homes in it MINUS the ones that already got re-roofed -- the unique edge no competitor has.

'Already re-roofed' evidence = a re-roof permit on record (age_source in permit/measured) OR the
satellite showing a recent reset. Eliminative, not additive: we never claim 'this roof is dying,'
we only remove the ones a roofer would waste a knock/stamp on.

Data source: fence-outreach/dataset/out/leads_enriched.parquet (folio, lat, lng, age_source,
satellite_reset_detected). This is the paid product's core query -- ready, not surfaced."""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "..", "..", "fence-outreach", "dataset", "out", "leads_enriched.parquet")


def eliminate(homes):
    """Pure: drop homes with re-roof evidence. `homes` = list of dicts with keys
    age_source and satellite_reset_detected. Returns the homes worth targeting."""
    out = []
    for h in homes:
        permitted = h.get("age_source") in ("permit", "measured")
        reset = bool(h.get("satellite_reset_detected"))
        if not permitted and not reset:
            out.append(h)
    return out


def zone_leads(bbox, src=DEFAULT_SRC):
    """(w,s,e,n) -> homes in the hail zone with NO re-roof evidence. Empty if the
    enriched source is not built yet."""
    if not os.path.exists(src):
        return []
    df = pd.read_parquet(src)
    w, s, e, n = bbox
    df = df[(df["lng"] >= w) & (df["lng"] <= e) & (df["lat"] >= s) & (df["lat"] <= n)]
    return eliminate(df.to_dict("records"))
