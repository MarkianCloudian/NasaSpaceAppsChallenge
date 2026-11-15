"""The shared global 0.05° grid (MODIS CMG, research D-006, task T037).

7200 × 3600 cells, EPSG:4326, cell edges at multiples of 0.05°, origin (−180, 90): row 0 is the
northernmost row, column 0 starts at −180°. MOD11C3, MOD13C2 and MCD12C1 are published natively
on this grid. Cell area varies with latitude and is the weight for area statistics/percentiles.

Layers are stored as single-band float32 GeoTIFFs (deflate, tiled, nodata NaN).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds

NCOLS, NROWS = 7200, 3600
CELL_DEG = 0.05
CRS = "EPSG:4326"
LON0, LAT0 = -180.0, 90.0
TRANSFORM = from_origin(LON0, LAT0, CELL_DEG, CELL_DEG)
# authalic (equal-area) Earth radius, so that summed cell areas equal the sphere of the same area
EARTH_RADIUS_KM = 6371.0072
GTIFF_PROFILE = {
    "driver": "GTiff",
    "dtype": "float32",
    "count": 1,
    "crs": CRS,
    "nodata": float("nan"),
    "compress": "deflate",
    "tiled": True,
    "blockxsize": 512,
    "blockysize": 512,
}


def cell_centres() -> tuple[np.ndarray, np.ndarray]:
    """(lat of every row centre (3600,), lon of every column centre (7200,)), degrees."""
    lat = LAT0 - (np.arange(NROWS) + 0.5) * CELL_DEG
    lon = LON0 + (np.arange(NCOLS) + 0.5) * CELL_DEG
    return lat, lon


def cell_area_km2(row) -> np.ndarray | float:
    """Area of one cell in `row` (int or array of ints), km²: R²·Δλ·(sin φ_north − sin φ_south)."""
    r = np.asarray(row, dtype="float64")
    north = np.radians(LAT0 - r * CELL_DEG)
    south = np.radians(LAT0 - (r + 1) * CELL_DEG)
    area = EARTH_RADIUS_KM**2 * math.radians(CELL_DEG) * (np.sin(north) - np.sin(south))
    return float(area) if np.ndim(row) == 0 else area


def row_col(lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """Row and column of the cell containing each lat/lon (lon wrapped to −180…180)."""
    lat = np.asarray(lat, dtype="float64")
    lon = (np.asarray(lon, dtype="float64") + 180.0) % 360.0 - 180.0
    rows = np.clip(np.floor((LAT0 - lat) / CELL_DEG), 0, NROWS - 1).astype(np.int64)
    cols = np.clip(np.floor((lon - LON0) / CELL_DEG), 0, NCOLS - 1).astype(np.int64)
    return rows, cols


def write_layer(path, array: np.ndarray, tags: dict | None = None) -> Path:
    """Write a full-grid layer (3600 × 7200) as compressed float32 GeoTIFF."""
    a = np.asarray(array, dtype="float32")
    if a.shape != (NROWS, NCOLS):
        raise ValueError(f"layer must be {NROWS} × {NCOLS}, got {a.shape}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", width=NCOLS, height=NROWS, transform=TRANSFORM, **GTIFF_PROFILE
    ) as ds:
        ds.write(a, 1)
        if tags:
            ds.update_tags(**{k: str(v) for k, v in tags.items()})
    return path


def read_layer(path) -> np.ndarray:
    """Full layer as float32 (3600 × 7200), NaN where no data."""
    with rasterio.open(path) as ds:
        _check_grid(ds, path)
        return ds.read(1, masked=False).astype("float32")


def read_window(path, west: float, south: float, east: float, north: float):
    """Cells overlapping a lat/lon box: (float32 array, rasterio transform of the window)."""
    with rasterio.open(path) as ds:
        _check_grid(ds, path)
        w = from_bounds(west, south, east, north, ds.transform)
        r0, c0 = max(int(math.floor(w.row_off)), 0), max(int(math.floor(w.col_off)), 0)
        r1 = min(int(math.ceil(w.row_off + w.height)), NROWS)
        c1 = min(int(math.ceil(w.col_off + w.width)), NCOLS)
        win = Window(c0, r0, max(c1 - c0, 0), max(r1 - r0, 0))
        return ds.read(1, window=win).astype("float32"), ds.window_transform(win)


def _check_grid(ds, path) -> None:
    if (ds.height, ds.width) != (NROWS, NCOLS) or not ds.transform.almost_equals(TRANSFORM):
        raise ValueError(
            f"{path}: not on the 0.05° CMG grid ({ds.height}×{ds.width}, {ds.transform})"
        )
