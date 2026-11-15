"""Fake source adapters for refinement tests (task T034); no network.

`fake_registry(cache_dir)` returns a registry whose `get(source_id)` gives:
  fx-fine-dem  a 30 m (1 arc-second) DEM GeoTIFF over the request bbox: a plane rising
               eastwards with a known slope (`DEM_SLOPE_DEG`)
  fx-emit      one synthetic EMIT L2B MIN granule centred on the request bbox (gypsum with a
               montmorillonite block, see minerals_synthetic.py)
Adapters follow the contract shape: probe(), fetch(request) -> FetchResult, plus search()
for `emit_coverage`. Requests use `bounding_box` [west, south, east, north].
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np

from analogfinder.storage import fingerprint
from analogfinder.types import FetchResult
from tests.fixtures.minerals_synthetic import EMIT_N, EMIT_STEP, write_emit_granule

DEM_SLOPE_DEG = 5.0
ARCSEC = 1 / 3600


def write_dem(path: Path, bbox) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    west, south, east, north = bbox
    nx = max(int(math.ceil((east - west) / ARCSEC)), 3)
    ny = max(int(math.ceil((north - south) / ARCSEC)), 3)
    lat_c = (north + south) / 2
    dx_m = ARCSEC * math.pi * 6371000 / 180 * math.cos(math.radians(lat_c))
    row = np.arange(nx) * dx_m * math.tan(math.radians(DEM_SLOPE_DEG))
    z = np.tile(row, (ny, 1)).astype("float32") + 500.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=nx,
        height=ny,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(west, north, ARCSEC, ARCSEC),
        nodata=-9999.0,
    ) as ds:
        ds.write(z, 1)
    return path


def write_emit(path: Path, bbox) -> Path:
    write_emit_granule(path)
    lat_c, lon_c = (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
    gt = [
        lon_c - EMIT_N / 2 * EMIT_STEP,
        EMIT_STEP,
        0.0,
        lat_c + EMIT_N / 2 * EMIT_STEP,
        0.0,
        -EMIT_STEP,
    ]
    with h5py.File(path, "r+") as h:
        h.attrs["geotransform"] = np.array(gt)
    return path


class FakeSource:
    def __init__(self, source_id: str, cache_dir: Path, writer, filename: str):
        self.source_id, self.cache_dir = source_id, Path(cache_dir)
        self.writer, self.filename = writer, filename
        self.entry = {"source_id": source_id, "dataset_version": "fixture", "fallback": None}
        self.fetches = 0

    def probe(self):
        return SimpleNamespace(reachable=True, login_present=True, error=None)

    def search(self, request: dict) -> list:
        return [{"source_id": self.source_id, "bbox": list(request["bounding_box"])}]

    def fetch(self, request: dict) -> FetchResult:
        d = self.cache_dir / self.source_id / fingerprint(request)
        if not d.exists():
            d.mkdir(parents=True)
            self.writer(d / self.filename, request["bounding_box"])
        self.fetches += 1
        return FetchResult(d, self.source_id, None)


class FakeRegistry:
    def __init__(self, sources: dict[str, FakeSource]):
        self._s = sources

    def get(self, source_id: str) -> FakeSource:
        return self._s[source_id]

    def __contains__(self, source_id: str) -> bool:
        return source_id in self._s


def fake_registry(cache_dir: Path) -> FakeRegistry:
    return FakeRegistry(
        {
            "fx-fine-dem": FakeSource("fx-fine-dem", cache_dir, write_dem, "dem.tif"),
            "fx-emit": FakeSource(
                "fx-emit", cache_dir, write_emit, "EMIT_L2B_MIN_002_20230101T000000_0000000_000.nc"
            ),
        }
    )
