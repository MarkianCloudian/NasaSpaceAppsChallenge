"""refine/terrain.py: synthetic DEMs through a fake source registry (T050)."""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from analogfinder.refine import terrain
from analogfinder.sources.base import Source, SourceRegistry

PX = 1 / 3600  # 1 arc-second
M_PER_DEG = terrain.EARTH_RADIUS_M * math.pi / 180


class FakeDem(Source):
    """Writes one GeoTIFF with elevation `fn(lat, lon)` over the requested bbox."""

    fn = staticmethod(lambda lat, lon: 0.0 * lat)
    min_lat = -90.0
    calls = 0

    def probe(self):
        raise NotImplementedError

    def _download(self, request, target):
        type(self).calls += 1
        w, s, e, n = request["bbox"]
        s = max(s, self.min_lat)
        if s >= n:
            return
        cols, rows = round((e - w) / PX), round((n - s) / PX)
        lat = n - PX * (np.arange(rows) + 0.5)
        lon = w + PX * (np.arange(cols) + 0.5)
        z = self.fn(lat[:, None], lon[None, :]).astype("float32")
        with rasterio.open(
            target / "dem.tif",
            "w",
            driver="GTiff",
            height=rows,
            width=cols,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(w, n, PX, PX),
            nodata=-9999.0,
        ) as dst:
            dst.write(z, 1)


def make_ctx(tmp_path, primary_fn, fallback_fn=None, primary_min_lat=-90.0, min_cov=0.5):
    class Primary(FakeDem):
        fn = staticmethod(primary_fn)
        min_lat = primary_min_lat
        calls = 0

    class Fallback(FakeDem):
        fn = staticmethod(fallback_fn or primary_fn)
        calls = 0

    def entry(sid, fb):
        return {
            "source_id": sid,
            "route": "fake",
            "dataset_version": "t",
            "rate_limit": {"requests": 1000, "per_seconds": 1},
            "retries": 0,
            "fallback": fb,
        }

    reg = SourceRegistry(
        {
            "nasadem-pc": Primary(entry("nasadem-pc", "copdem-glo30-pc"), tmp_path),
            "copdem-glo30-pc": Fallback(entry("copdem-glo30-pc", None), tmp_path),
        }
    )
    crit = lambda cid, q: SimpleNamespace(  # noqa: E731
        id=cid,
        quantity=q,
        baseline_m=30,
        evaluation_scale="refinement",
        earth_sources=("nasadem-pc", "copdem-glo30-pc"),
    )
    profile = SimpleNamespace(
        criteria=(
            crit("traverse_slope", "slope_p90"),
            crit("roughness", "rms_roughness"),
            SimpleNamespace(
                id="x",
                quantity="slope_p90",
                baseline_m=926,
                evaluation_scale="grid",
                earth_sources=("etopo-2022",),
            ),
        )
    )
    ctx = SimpleNamespace(
        profile=profile, sources=reg, settings={"coverage": {"min_coverage_fraction": min_cov}}
    )
    return ctx, Primary, Fallback


def area(lat=10.0, lon=20.0, r=2.0, aid="p-10.00_20.00"):
    return SimpleNamespace(area_id=aid, footprint=(lat, lon, r))


def test_ramp_slope_and_zero_roughness(tmp_path):
    slope_deg = 10.0
    tan = math.tan(math.radians(slope_deg))
    ctx, *_ = make_ctx(tmp_path, lambda lat, lon: tan * M_PER_DEG * (lat - 10))  # rises northwards
    res = terrain.refine(area(), ctx)
    assert res.group == "terrain" and res.source_id == "nasadem-pc"
    assert res.coverage == pytest.approx(1.0)
    assert res.values["traverse_slope"] == pytest.approx(slope_deg, abs=0.1)
    assert res.values["roughness"] == pytest.approx(0.0, abs=1e-3)
    assert set(res.values) == {"traverse_slope", "roughness"}  # grid-only criterion ignored


def test_roughness_of_checkerboard(tmp_path):
    def noisy(lat, lon):
        i = np.round((lat - 10) / PX).astype(int)
        j = np.round((lon - 20) / PX).astype(int)
        return np.where((i + j) % 2 == 0, 1.0, -1.0)

    ctx, *_ = make_ctx(tmp_path, noisy)
    res = terrain.refine(area(), ctx)
    assert res.values["roughness"] == pytest.approx(2.0, rel=0.05)  # all differences are +-2


def test_baseline_area_averaging_removes_fine_noise():
    rng = np.random.default_rng(1)
    z = rng.normal(0, 5, (600, 600))
    tr = from_origin(20.0, 10.2, PX, PX)
    fine = terrain.terrain_stats(z, tr, 10.1, 20.1, 2.0, 30.0)
    coarse = terrain.terrain_stats(z, tr, 10.1, 20.1, 2.0, 300.0)
    assert coarse["rms_roughness"] < fine["rms_roughness"]
    assert coarse["slope_p90"] < fine["slope_p90"]


def test_deterministic_and_cached(tmp_path):
    ctx, Primary, _ = make_ctx(
        tmp_path, lambda lat, lon: 100 * np.sin(lat * 900) * np.cos(lon * 900)
    )
    a, b = terrain.refine(area(), ctx), terrain.refine(area(), ctx)
    assert a == b
    assert Primary.calls == 1  # second run served from the per-area cache


def test_low_coverage_uses_fallback(tmp_path):
    flat = lambda lat, lon: 0.0 * lat  # noqa: E731
    slope = lambda lat, lon: 50.0 * (lat - 10) / PX * PX * M_PER_DEG / 50.0  # noqa: E731
    ctx, Primary, Fallback = make_ctx(
        tmp_path, flat, fallback_fn=slope, primary_min_lat=10.5, min_cov=0.5
    )  # primary has no data below 10.5 deg -> circle at 10.0 uncovered
    res = terrain.refine(area(), ctx)
    assert res.source_id == "copdem-glo30-pc"
    assert Fallback.calls == 1 and res.coverage == pytest.approx(1.0)


def test_insufficient_everywhere_is_nan(tmp_path):
    ctx, *_ = make_ctx(tmp_path, lambda lat, lon: 0.0 * lat, primary_min_lat=20.0)
    ctx.sources._sources["copdem-glo30-pc"].min_lat = 20.0
    res = terrain.refine(area(), ctx)
    assert res.source_id is None and res.coverage is None
    assert all(math.isnan(v) for v in res.values.values())


def test_only_selected_areas_fetched_and_counted(tmp_path, caplog):
    ctx, Primary, _ = make_ctx(tmp_path, lambda lat, lon: 0.0 * lat)
    selected = [area(10.0, 20.0, aid="a"), area(30.0, 40.0, aid="b")]
    with caplog.at_level(logging.INFO, logger="analogfinder.refine.terrain"):
        out = terrain.refine_selected(selected, ctx)
    assert set(out) == {"a", "b"} and Primary.calls == 2
    assert "2 area(s) selected" in caplog.text
