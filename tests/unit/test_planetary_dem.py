"""T072: Mars DEM targets on synthetic planes with a known slope, mosaics, catalogue, cache."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from analogfinder.planetary import dem
from tests.conftest import ROOT

LAT0, LON0, R_KM = 18.44, 77.45, 20.0
SLOPE = 5.0
EQC = CRS.from_proj4(f"+proj=eqc +lat_ts=0 +lon_0=0 +R={dem.MARS_RADIUS_M:.0f} +units=m +no_defs")


def geo_plane(path, res_deg=0.003374, half=None, noise=0.0):
    """Geographic Mars DEM: plane rising eastwards with ground slope SLOPE (int16-like float)."""
    w, s, e, n = dem.footprint_bbox(LAT0, LON0, R_KM + 10)
    nx, ny = math.ceil((e - w) / res_deg), math.ceil((n - s) / res_deg)
    lat = n - (np.arange(ny) + 0.5) * res_deg
    lon = w + (np.arange(nx) + 0.5) * res_deg
    east_m = (lon[None, :] - LON0) * dem.MARS_RADIUS_M * np.cos(np.radians(lat[:, None]))
    z = (np.radians(1) * east_m * math.tan(math.radians(SLOPE))).astype("float32")
    z += np.random.default_rng(0).normal(0, noise, z.shape).astype("float32") if noise else 0
    if half == "west":
        z[:, nx // 2 :] = -32768
    elif half == "east":
        z[:, : nx // 2] = -32768
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=nx,
        height=ny,
        count=1,
        dtype="float32",
        crs=dem.MARS_GEO,
        transform=from_origin(w, n, res_deg, res_deg),
        nodata=-32768,
    ) as ds:
        ds.write(z, 1)
    return str(path)


def eqc_plane(path, res_m=20.0):
    """Projected (CTX-like equirectangular, clon 0) Mars DTM with ground slope SLOPE eastwards."""
    w, s, e, n = dem.footprint_bbox(LAT0, LON0, R_KM + 10)
    k = math.pi / 180 * dem.MARS_RADIUS_M
    x0, x1, y0, y1 = w * k, e * k, s * k, n * k
    nx, ny = math.ceil((x1 - x0) / res_m), math.ceil((y1 - y0) / res_m)
    x = x0 + (np.arange(nx) + 0.5) * res_m
    y = y1 - (np.arange(ny) + 0.5) * res_m
    lat = np.degrees(y / dem.MARS_RADIUS_M)
    east_ground = (x[None, :] - LON0 * k) * np.cos(np.radians(lat[:, None]))
    z = (east_ground * math.tan(math.radians(SLOPE))).astype("float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=nx,
        height=ny,
        count=1,
        dtype="float32",
        crs=EQC,
        transform=from_origin(x0, y1, res_m, res_m),
        nodata=-32767,
    ) as ds:
        ds.write(z, 1)
    return str(path)


def test_regional_plane_slope(tmp_path):
    path = geo_plane(tmp_path / "mola.tif")
    r = dem.regional(path, LAT0, LON0, R_KM, 926)
    assert r["slope_p90"] == pytest.approx(SLOPE, abs=0.05) and r["coverage"] == 1.0
    f = dem.fine([path], LAT0, LON0, R_KM, 926)
    assert f["rms_roughness"] < 0.05  # geographic plane, no warp: only decimation residual


def test_fine_projected_plane_slope_and_zero_roughness(tmp_path):
    r = dem.fine([eqc_plane(tmp_path / "ctx.tif")], LAT0, LON0, R_KM, 30)
    assert r["slope_p90"] == pytest.approx(SLOPE, abs=0.1)
    # warping 20 m equirectangular pixels onto a 30 m geographic grid (non-integer ratio) leaves a
    # small residual: ~3 % of the 2.6 m elevation step per cell on a 5° plane; a plane read
    # without reprojection stays < 0.05 m (see test_regional_plane_slope)
    assert r["rms_roughness"] < 0.2 and r["coverage"] == 1.0


def test_noise_gives_roughness(tmp_path):
    r = dem.fine([geo_plane(tmp_path / "n.tif", res_deg=0.0003, noise=2.0)], LAT0, LON0, R_KM, 30)
    assert r["rms_roughness"] > 0.3


def test_mosaic_two_halves_and_partial_coverage(tmp_path):
    west = geo_plane(tmp_path / "w.tif", half="west")
    east = geo_plane(tmp_path / "e.tif", half="east")
    both = dem.regional(west, LAT0, LON0, R_KM, 926)
    assert 0.4 < both["coverage"] < 0.6
    t, w, h = dem.grid_for(LAT0, LON0, R_KM, 926)
    z = dem.mosaic([west, east], t, w, h)
    st = dem.terrain_stats(z, t, LAT0, LON0, R_KM)
    assert st["coverage"] == 1.0 and st["slope_p90"] == pytest.approx(SLOPE, abs=0.1)


class FakeClient:
    def __init__(self, items):
        self._items = items

    def search(self, collections, bbox):
        return SimpleNamespace(items=lambda: iter(self._items))


def item(iid, bbox, href=None):
    assets = {"dtm": SimpleNamespace(href=href or f"{iid}.tif")} if href is not False else {}
    return SimpleNamespace(id=iid, bbox=bbox, assets=assets)


def test_ctx_items_filtered_and_sorted():
    w, s, e, n = dem.footprint_bbox(LAT0, LON0, R_KM)
    items = [
        item("small", [w, s, (w + e) / 2, (s + n) / 2]),
        item("full", [w - 1, s - 1, e + 1, n + 1]),
        item("no-dtm", [w, s, e, n], href=False),
    ]
    got = dem.ctx_dtm_items({"collection": "c"}, LAT0, LON0, R_KM, client=FakeClient(items))
    assert [g[0] for g in got] == ["full", "small"] and got[0][2] == 1.0


def test_extract_profile_criteria_and_cache(tmp_path):
    profile = json.loads((ROOT / "profiles" / "mars-rover-jezero.json").read_text())
    mola, ctx = geo_plane(tmp_path / "mola.tif"), eqc_plane(tmp_path / "ctx.tif")
    sources = {
        "sources": [
            {"source_id": "mola-hrsc-blend", "endpoint": mola, "dataset_version": "v2"},
            {"source_id": "usgs-mars-dtm-stac", "collection": "c", "dataset_version": "1"},
        ]
    }
    w, s, e, n = dem.footprint_bbox(LAT0, LON0, R_KM)
    client = FakeClient([item("CTX1", [w - 1, s - 1, e + 1, n + 1], href=ctx)])
    rows = {
        r["criterion"]: r for r in dem.extract(profile, sources, client, data_dir=tmp_path / "d")
    }
    assert set(rows) == {"regional_slope", "traverse_slope", "roughness"}
    assert (
        rows["regional_slope"]["baseline_m"] == 926 and rows["traverse_slope"]["baseline_m"] == 30
    )
    assert rows["regional_slope"]["value"] == pytest.approx(SLOPE, abs=0.1)
    assert rows["traverse_slope"]["source_id"] == "usgs-mars-dtm-stac"
    assert rows["traverse_slope"]["items"] == ["CTX1"]
    # cached: the DEM files can disappear and the numbers stay the same
    (tmp_path / "mola.tif").unlink()
    (tmp_path / "ctx.tif").unlink()
    again = {
        r["criterion"]: r for r in dem.extract(profile, sources, client, data_dir=tmp_path / "d")
    }
    assert again["roughness"]["value"] == rows["roughness"]["value"]


def test_unknown_target_source_is_reported():
    profile = json.loads((ROOT / "profiles" / "mars-rover-jezero.json").read_text())
    rows = dem.extract(profile, {"sources": []}, FakeClient([]))
    assert all("unknown target source" in r["error"] for r in rows)
