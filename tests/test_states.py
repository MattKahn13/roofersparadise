from roofersparadise.ingest.states import tag_states


def test_tag_states_florida_and_ny():
    pts = [(27.95, -82.45), (40.71, -74.00)]  # Tampa FL, NYC
    tags = tag_states(pts)
    assert tags[0] == "Florida"
    assert tags[1] in ("New York", None)


def test_tag_states_ocean_is_none():
    tags = tag_states([(25.0, -90.0)])  # Gulf of Mexico
    assert tags[0] is None


def test_empty_input():
    assert tag_states([]) == []
