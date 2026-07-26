"""Data assertions -- the gatekeeper. Failures are returned (and logged by the caller
to data/_audit_log.parquet), never silently passed."""


def check_rows(rows):
    problems = []
    for i, r in enumerate(rows):
        hi = r.get("hail_in", 0)
        if not (0.5 <= hi <= 6.0):
            problems.append(f"row {i}: hail_in {hi} out of range 0.5-6.0")
        lat, lng = r.get("lat", 999), r.get("lng", 999)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            problems.append(f"row {i}: bad coords ({lat},{lng})")
    return problems
