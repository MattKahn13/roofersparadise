import numpy as np
from roofersparadise.ingest.mrms import cells_from_grid, MESH_MIN_MM


def test_mesh_floor_is_marginal_hail():
    assert MESH_MIN_MM == 19.0


def test_cells_from_grid_thresholds_and_converts():
    # 2x2 grid; only [0,1] (=44.8mm) clears the 19mm floor
    arr = np.array([[5.0, 44.8], [-3.0, 0.0]])

    def tr(c, r):  # (col+0.5,row+0.5) -> (lon,lat)
        return (-82.0 + c * 0.01, 27.5 + r * 0.01)

    cells = cells_from_grid(arr, tr)
    assert len(cells) == 1
    lat, lng, mm = cells[0]
    assert round(mm, 1) == 44.8
    # cell [row=0,col=1] -> transform(1.5, 0.5)
    assert abs(lng - (-82.0 + 1.5 * 0.01)) < 1e-9
    assert abs(lat - (27.5 + 0.5 * 0.01)) < 1e-9


def test_empty_grid_returns_no_cells():
    arr = np.array([[0.0, 5.0], [-3.0, 1.0]])
    assert cells_from_grid(arr, lambda c, r: (c, r)) == []
