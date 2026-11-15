"""T037."""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import xy

from analogfinder.grid import cells


def test_transform_cell_00_centre():
    x, y = xy(cells.TRANSFORM, 0, 0, offset="center")
    assert (x, y) == pytest.approx((-179.975, 89.975))
    lat, lon = cells.cell_centres()
    assert lat.shape == (3600,) and lon.shape == (7200,)
    assert (lat[0], lon[0], lat[-1], lon[-1]) == pytest.approx((89.975, -179.975, -89.975, 179.975))


def test_total_area_is_earth_surface():
    rows = np.arange(cells.NROWS)
    total = cells.cell_area_km2(rows).sum() * cells.NCOLS
    assert total == pytest.approx(510.07e6, rel=1e-3)
    # equator cell ≈ (0.05° × 111.2 km)² ≈ 30.9 km²; cells shrink towards the poles
    assert cells.cell_area_km2(1799) == pytest.approx(30.9, rel=0.01)
    assert cells.cell_area_km2(0) < cells.cell_area_km2(900) < cells.cell_area_km2(1799)


def test_row_col():
    r, c = cells.row_col([89.99, 0.01, -89.99], [-179.99, 0.01, 179.99])
    assert r.tolist() == [0, 1799, 3599] and c.tolist() == [0, 3600, 7199]
    assert cells.row_col(10.0, 190.0)[1] == cells.row_col(10.0, -170.0)[1]  # lon wraps


def test_write_read_layer_and_window(tmp_path):
    a = np.full((cells.NROWS, cells.NCOLS), np.nan, dtype="float32")
    r, c = cells.row_col(18.44, 77.45)
    a[r, c] = 7.0
    p = cells.write_layer(tmp_path / "x.tif", a, tags={"layer_id": "x"})
    back = cells.read_layer(p)
    assert back.dtype == np.float32 and back[r, c] == 7.0 and np.isnan(back[0, 0])
    win, tr = cells.read_window(p, 77.3, 18.3, 77.6, 18.6)
    assert win.shape == (6, 6) and np.nansum(win) == 7.0
    assert xy(tr, 0, 0, offset="ul") == pytest.approx((77.3, 18.6))
    import rasterio

    with rasterio.open(p) as ds:
        assert ds.profile["compress"] == "deflate" and ds.profile["tiled"]


def test_write_rejects_wrong_shape(tmp_path):
    with pytest.raises(ValueError, match="3600"):
        cells.write_layer(tmp_path / "bad.tif", np.zeros((10, 10)))
