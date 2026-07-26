from roofersparadise.ingest.premium import eliminate


def test_eliminate_drops_reroofed_homes():
    homes = [
        {"folio": "A", "age_source": "proxy", "satellite_reset_detected": False},   # keep
        {"folio": "B", "age_source": "permit", "satellite_reset_detected": False},  # drop (permit)
        {"folio": "C", "age_source": "proxy", "satellite_reset_detected": True},    # drop (satellite reset)
        {"folio": "D", "age_source": "measured", "satellite_reset_detected": False},# drop (measured=permit)
    ]
    kept = eliminate(homes)
    assert [h["folio"] for h in kept] == ["A"]


def test_eliminate_empty():
    assert eliminate([]) == []
