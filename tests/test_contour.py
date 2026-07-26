from roofersparadise.ingest.contour import chaikin, BANDS_IN, _band_index


def test_bands_are_nws_thresholds():
    assert BANDS_IN == [0.75, 1.0, 1.75, 2.5]


def test_band_index():
    assert _band_index(0.5) == 0
    assert _band_index(0.8) == 1
    assert _band_index(1.2) == 2
    assert _band_index(2.6) == 4


def test_chaikin_smooths_and_closes():
    sq = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    out = chaikin(sq, iterations=2)
    assert len(out) > len(sq)          # more vertices after smoothing
    assert out[0] == out[-1]           # ring stays closed
