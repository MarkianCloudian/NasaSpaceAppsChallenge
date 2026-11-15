"""Tiny synthetic 0.05° grid with every data-model grid layer (task T034).

20 rows × 40 columns, row 0 centred at 24.0 − 0.025° N, column 0 at 10.0 + 0.025° E.
Regions (row slice, column slice):
  blob_a        Mars-like (barren, dry, bare, large thermal swing, gentle slopes)
  blob_b        Mars-like and a little drier than blob_a (should rank first)
  veto_area     Mars-like except dense vegetation (fails the no_vegetation veto)
  missing_area  Mars-like but climate layers are NaN (UNKNOWN, lowers confidence)
  sea           last two columns: not land
Everything else is a vegetated, wetter background that should not survive screening.
All numbers are invented test values, not data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from analogfinder.types import LandIndex

ROWS, COLS, CELL = 20, 40, 0.05
LAT_TOP, LON_LEFT = 24.0, 10.0

REGIONS = {
    "blob_a": (slice(2, 9), slice(2, 11)),
    "blob_b": (slice(11, 18), slice(26, 36)),
    "veto_area": (slice(2, 9), slice(15, 22)),
    "missing_area": (slice(12, 18), slice(13, 20)),
    "sea": (slice(0, ROWS), slice(COLS - 2, COLS)),
}

CLIMATE = (
    "t2m_mean",
    "t2m_min",
    "t2m_max",
    "rh2m_mean",
    "ws10m_mean",
    "precip_annual",
    "insolation_mean",
)
LANDCOVER = (
    "lc_frac_water",
    "lc_frac_forest",
    "lc_frac_grass_shrub",
    "lc_frac_wetland",
    "lc_frac_cropland",
    "lc_frac_urban",
    "lc_frac_snow_ice",
    "lc_frac_barren",
)
BACKGROUND = {
    "lc_frac_water": 0.0,
    "lc_frac_forest": 0.1,
    "lc_frac_grass_shrub": 0.5,
    "lc_frac_wetland": 0.0,
    "lc_frac_cropland": 0.15,
    "lc_frac_urban": 0.05,
    "lc_frac_snow_ice": 0.0,
    "lc_frac_barren": 0.2,
    "lst_day_max": 35.0,
    "lst_night_min": 12.0,
    "lst_mean": 22.0,
    "lst_amp": 15.0,
    "ndvi_max": 0.35,
    "t2m_mean": 18.0,
    "t2m_min": 8.0,
    "t2m_max": 30.0,
    "rh2m_mean": 55.0,
    "ws10m_mean": 3.0,
    "precip_annual": 600.0,
    "insolation_mean": 5.0,
    "elev_mean": 400.0,
    "relief": 300.0,
    "slope_p90_1km": 6.0,
    "elev_std": 80.0,
}
MARS_LIKE = {
    "lc_frac_forest": 0.0,
    "lc_frac_grass_shrub": 0.05,
    "lc_frac_cropland": 0.0,
    "lc_frac_urban": 0.0,
    "lc_frac_barren": 0.95,
    "lst_day_max": 60.0,
    "lst_night_min": 5.0,
    "lst_mean": 30.0,
    "lst_amp": 35.0,
    "ndvi_max": 0.05,
    "rh2m_mean": 12.0,
    "precip_annual": 8.0,
    "ws10m_mean": 4.0,
    "insolation_mean": 6.5,
    "elev_mean": 1200.0,
    "relief": 150.0,
    "slope_p90_1km": 2.0,
    "elev_std": 40.0,
}


@dataclass
class SyntheticGrid:
    layers: dict[str, np.ndarray] = field(default_factory=dict)  # float32 (ROWS, COLS)
    shape: tuple[int, int] = (ROWS, COLS)
    cell_deg: float = CELL
    lat_top: float = LAT_TOP
    lon_left: float = LON_LEFT

    @property
    def land_mask(self) -> np.ndarray:
        return self.layers["land_mask"] > 0.5

    def land_index(self) -> LandIndex:
        rows, cols = np.nonzero(self.land_mask)
        lat = self.lat_top - (rows + 0.5) * self.cell_deg
        lon = self.lon_left + (cols + 0.5) * self.cell_deg
        km = self.cell_deg * 111.195
        area = km * km * np.cos(np.radians(lat))
        return LandIndex(rows.astype(np.int32), cols.astype(np.int32), lat, lon, area)

    def land_vector(self, layer_id: str) -> np.ndarray:
        li = self.land_index()
        return self.layers[layer_id][li.rows, li.cols].astype("float64")

    def region_mask(self, name: str) -> np.ndarray:
        m = np.zeros(self.shape, bool)
        m[REGIONS[name]] = True
        return m

    def write_geotiffs(self, directory: Path) -> dict[str, Path]:
        """One single-band float32 GeoTIFF per layer (EPSG:4326), for grid-reading tests."""
        import rasterio
        from rasterio.transform import from_origin

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        tr = from_origin(self.lon_left, self.lat_top, self.cell_deg, self.cell_deg)
        out = {}
        for name, arr in self.layers.items():
            p = directory / f"{name}.tif"
            with rasterio.open(
                p,
                "w",
                driver="GTiff",
                width=self.shape[1],
                height=self.shape[0],
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=tr,
                nodata=np.nan,
            ) as ds:
                ds.write(arr.astype("float32"), 1)
            out[name] = p
        return out


def build_synthetic_grid() -> SyntheticGrid:
    g = SyntheticGrid()
    full = lambda v: np.full((ROWS, COLS), v, dtype="float32")  # noqa: E731
    g.layers = {k: full(v) for k, v in BACKGROUND.items()}
    g.layers["land_mask"] = full(1.0)
    for region in ("blob_a", "blob_b", "veto_area", "missing_area"):
        for k, v in MARS_LIKE.items():
            g.layers[k][REGIONS[region]] = v
    g.layers["precip_annual"][REGIONS["blob_b"]] = 3.0  # blob_b is the driest
    g.layers["rh2m_mean"][REGIONS["blob_b"]] = 10.0
    veto = REGIONS["veto_area"]
    g.layers["ndvi_max"][veto] = 0.6
    g.layers["lc_frac_forest"][veto] = 0.6
    g.layers["lc_frac_barren"][veto] = 0.05
    for k in CLIMATE:
        g.layers[k][REGIONS["missing_area"]] = np.nan
    sea = REGIONS["sea"]
    for k in g.layers:
        g.layers[k][sea] = np.nan
    g.layers["land_mask"][sea] = 0.0
    for k in LANDCOVER:
        g.layers[k][sea] = 0.0
    g.layers["lc_frac_water"][sea] = 1.0
    return g
