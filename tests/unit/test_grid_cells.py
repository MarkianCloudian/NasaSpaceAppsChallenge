from __future__ import annotations

import numpy as np
import rasterio

from analogfinder.grid import cells


def test_transform_cell_00_centre() -> None:
    x, y = cells.TRANSFORM * (0.5, 0.5)
    assert (x, y) == (-179.975, 89.975) or (round(x, 6), round(y, 6)) == (-179.975, 89.975)
    lat, lon = cells.cell_centres()
    assert lat.shape == (3600,) and lon.shape == (7200,)
    assert np.isclose(lat[0], 89.975) and np.isclose(lon[0], -179.975)
    assert np.isclose(lat[-1], -89.975) and np.isclose(lon[-1], 179.975)


def test_total_area() -> None:
    total = cells.cell_area_km2(np.arange(cells.N_ROWS)).sum() * cells.N_COLS
    assert abs(total - 510e6) / 510e6 < 0.005
    assert cells.cell_area_km2(0) < cells.cell_area_km2(1800)


def test_roundtrip_and_window(tmp_path) -> None:
    arr = np.arange(cells.N_ROWS * cells.N_COLS, dtype="float32").reshape(cells.N_ROWS, -1)
    arr[0, 0] = np.nan
    p = tmp_path / "l.tif"
    cells.write_layer(p, arr)
    with rasterio.open(p) as src:
        assert src.profile["compress"].lower() == "deflate"
        assert src.profile["tiled"] and src.dtypes[0] == "float32"
    assert np.array_equal(cells.read_layer(p), arr, equal_nan=True)
    data, tr = cells.read_window(p, 10.0, 10.1, 20.0, 20.15)
    assert data.shape == (2, 3)
    assert np.array_equal(data, arr[1598:1600, 4000:4003])
    assert np.isclose(tr.c, 20.0) and np.isclose(tr.f, 10.1)
