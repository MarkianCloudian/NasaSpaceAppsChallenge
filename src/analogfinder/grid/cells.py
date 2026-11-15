"""Grid definition (research D-006): NASA MODIS Climate Modelling Grid, 0.05°, EPSG:4326."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds

log = logging.getLogger("analogfinder.grid.cells")

N_COLS = 7200
N_ROWS = 3600
CELL_DEG = 0.05
CRS = "EPSG:4326"
ORIGIN_LON = -180.0
ORIGIN_LAT = 90.0
EARTH_RADIUS_KM = 6371.0088  # mean radius (IUGG); spherical cell areas

TRANSFORM = Affine(CELL_DEG, 0.0, ORIGIN_LON, 0.0, -CELL_DEG, ORIGIN_LAT)


def cell_centres() -> tuple[np.ndarray, np.ndarray]:
    """Return (lat, lon) 1-D arrays of cell-centre coordinates (rows, cols); row 0 = 90°N."""
    lat = ORIGIN_LAT - (np.arange(N_ROWS, dtype=np.float64) + 0.5) * CELL_DEG
    lon = ORIGIN_LON + (np.arange(N_COLS, dtype=np.float64) + 0.5) * CELL_DEG
    return lat, lon


def cell_area_km2(row: int | np.ndarray) -> float | np.ndarray:
    """Area (km²) of a cell in the given row(s), on a sphere; same for every column."""
    row = np.asarray(row)
    north = np.radians(ORIGIN_LAT - row * CELL_DEG)
    south = np.radians(ORIGIN_LAT - (row + 1) * CELL_DEG)
    area = EARTH_RADIUS_KM**2 * np.radians(CELL_DEG) * (np.sin(north) - np.sin(south))
    return float(area) if area.ndim == 0 else area


def write_layer(path: Path, array: np.ndarray) -> None:
    """Write a full-grid layer as deflate-compressed, tiled float32 GeoTIFF (nodata NaN)."""
    if array.shape != (N_ROWS, N_COLS):
        raise ValueError(f"layer shape {array.shape} != {(N_ROWS, N_COLS)}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=N_ROWS,
        width=N_COLS,
        count=1,
        dtype="float32",
        crs=CRS,
        transform=TRANSFORM,
        nodata=np.nan,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(array.astype("float32", copy=False), 1)


def read_layer(path: Path) -> np.ndarray:
    """Read a full-grid layer as float32 array (N_ROWS, N_COLS)."""
    with rasterio.open(path) as src:
        return src.read(1).astype("float32", copy=False)


def read_window(
    path: Path, lat_min: float, lat_max: float, lon_min: float, lon_max: float
) -> tuple[np.ndarray, Affine]:
    """Read the cells covering a lat/lon box; returns (array, transform of the window)."""
    with rasterio.open(path) as src:
        win = from_bounds(lon_min, lat_min, lon_max, lat_max, transform=src.transform)
        col0 = max(int(np.floor(win.col_off + 1e-9)), 0)
        row0 = max(int(np.floor(win.row_off + 1e-9)), 0)
        col1 = min(int(np.ceil(win.col_off + win.width - 1e-9)), src.width)
        row1 = min(int(np.ceil(win.row_off + win.height - 1e-9)), src.height)
        window = Window(col0, row0, max(col1 - col0, 0), max(row1 - row0, 0))
        data = src.read(1, window=window).astype("float32", copy=False)
        return data, src.window_transform(window)
