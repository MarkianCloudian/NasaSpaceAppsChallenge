"""dem_block_stats (T042): cell- and grid-registered synthetic rasters, 36 values per cell."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine

from analogfinder.errors import ConfigError
from analogfinder.grid.builders import dem_block_stats as d

CELL = 30.0  # test cell size (deg): 12 x 6 cells of 6 x 6 pixels, pixel 5°
PX = CELL / 6
N_ROWS, N_COLS = 6, 12


def _write(path, arr, origin_lon, origin_lat, px=PX):
    t = Affine(px, 0, origin_lon, 0, -px, origin_lat)
    with rasterio.open(
        path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
        dtype="float32", crs="EPSG:4326", transform=t,
    ) as dst:  # fmt: skip
        dst.write(arr.astype("float32"), 1)


def _cell_raster():
    # elevation = cell id * 1000 + position inside the block (0..35): distinct per cell
    rows, cols = N_ROWS * 6, N_COLS * 6
    r, c = np.indices((rows, cols))
    cell_id = (r // 6) * N_COLS + (c // 6)
    return (cell_id * 1000 + (r % 6) * 6 + (c % 6)).astype("float64")


def test_cell_registered_exactly_36_values_and_edges(tmp_path):
    arr = _cell_raster()
    p = tmp_path / "cell.tif"
    _write(p, arr, -180.0, 90.0)
    out, reg = d.block_stats(p, 6, CELL)
    assert reg.kind == "cell" and reg.half_pixel_offset_deg == 0.0
    assert out["relief"].shape == (N_ROWS, N_COLS)
    # position values 0..35 inside each block: relief 35, mean = cell_id*1000 + 17.5
    assert np.allclose(out["relief"], 35.0)
    ids = np.arange(N_ROWS * N_COLS).reshape(N_ROWS, N_COLS)
    assert np.allclose(out["elev_mean"], ids * 1000 + 17.5)
    assert np.allclose(out["elev_std"], np.std(np.arange(36)))


def test_grid_registered_matches_cell_registered(tmp_path):
    base = _cell_raster()
    # grid-registered: nodes at the same positions; extra last column (= first, wrap) and row
    arr = np.pad(base, ((0, 1), (0, 1)), mode="edge")
    arr[:, -1] = arr[:, 0]
    p = tmp_path / "grid.tif"
    _write(p, arr, -180.0 - PX / 2, 90.0 + PX / 2)
    out, reg = d.block_stats(p, 6, CELL)
    assert reg.kind == "grid" and reg.half_pixel_offset_deg == pytest.approx(PX / 2)
    ids = np.arange(N_ROWS * N_COLS).reshape(N_ROWS, N_COLS)
    assert np.allclose(out["elev_mean"], ids * 1000 + 17.5)
    assert np.allclose(out["relief"], 35.0)  # edge nodes belong east/south: exactly 36 per cell


def test_unsupported_geometry_lists_found(tmp_path):
    p = tmp_path / "bad.tif"
    _write(p, np.zeros((10, 10)), -170.0, 80.0)
    with pytest.raises(ConfigError, match=r"found size 10 x 10, origin \(-170"):
        d.block_stats(p, 6, CELL)


def test_horn_slope_plane_and_flat():
    dx = np.full(3, 1000.0)
    z = np.tile(np.arange(5) * 1000.0, (5, 1))  # rises 1000 m per 1000 m eastwards
    s = d.horn_slope_deg(z, dx[:3], 1000.0)
    assert np.allclose(s[:, 1:-1], 45.0)
    assert np.allclose(d.horn_slope_deg(np.full((5, 5), 7.0), dx[:3], 1000.0), 0.0)


def test_slope_p90_on_tilted_block(tmp_path):
    rows, cols = N_ROWS * 6, N_COLS * 6
    arr = np.tile(np.arange(cols, dtype="float64") * 50.0, (rows, 1))
    p = tmp_path / "ramp.tif"
    _write(p, arr, -180.0, 90.0, px=PX)
    out, _ = d.block_stats(p, 6, CELL)
    assert np.isfinite(out["slope_p90_1km"]).all()
    assert (out["slope_p90_1km"] > 0).all()
