"""climatology_rest builder (T041): native grid, bilinear resampling, unit conversion, cache."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from analogfinder.errors import ConfigError, SourceError
from analogfinder.grid import cells
from analogfinder.grid.builders import climatology_rest as cr
from analogfinder.sources.power import PowerSource

ENTRY_SRC = {
    "source_id": "nasa-power",
    "dataset_version": "test",
    "rate_limit": {"requests": 1000, "per_seconds": 1},
    "endpoint": "https://power.example/api/",
    "retries": 0,
}


def test_assemble_and_bilinear():
    pts = [(lon, lat, lat + lon) for lon in (0.0, 1.0) for lat in (0.0, 1.0)]
    lat_ax, lon_ax, native = cr.assemble_native(pts)
    assert native.shape == (2, 2)
    out = cr.bilinear_to_grid(lat_ax, lon_ax, native, np.array([0.5, 0.25]), np.array([0.5, 1.0]))
    assert out[0, 0] == pytest.approx(1.0) and out[1, 1] == pytest.approx(1.25)


def test_bilinear_ignores_nan_cells():
    native = np.array([[1.0, np.nan], [1.0, 1.0]])
    out = cr.bilinear_to_grid(np.array([0.0, 1.0]), np.array([0.0, 1.0]), native, [0.5], [0.9])
    assert out[0, 0] == pytest.approx(1.0)
    allnan = np.full((2, 2), np.nan)
    out = cr.bilinear_to_grid(np.array([0.0, 1.0]), np.array([0.0, 1.0]), allnan, [0.5], [0.5])
    assert np.isnan(out[0, 0])


def test_read_tile_drops_fill(tmp_path):
    feat = lambda lon, lat, v: {  # noqa: E731
        "geometry": {"coordinates": [lon, lat, 0]},
        "properties": {"parameter": {"T2M": {"ANN": v}}},
    }
    p = tmp_path / "T2M.json"
    p.write_text(json.dumps({"features": [feat(1, 2, 3.5), feat(2, 2, -999)]}))
    assert cr.read_tile(p, "T2M", "ANN", (-999,)) == [(1.0, 2.0, 3.5)]


def test_land_tiles():
    land = np.zeros((cells.N_ROWS, cells.N_COLS), dtype=bool)
    land[0, 0] = True
    assert cr.land_tiles(land) == [(-180.0, 80.0, -170.0, 90.0)]


class FakeSource(PowerSource):
    def __init__(self, tmp_path):
        super().__init__(ENTRY_SRC, tmp_path, session=object())
        self.downloads = 0

    def _download(self, request, target):
        self.downloads += 1
        w, s, e, n = request["bbox"]
        for p in request["parameters"]:
            feats = [
                {
                    "geometry": {"coordinates": [lon, lat, 0]},
                    "properties": {"parameter": {p: {"ANN": 2.0}}},
                }
                for lon in np.arange(w + 0.3125, e, 0.625)
                for lat in np.arange(s + 0.25, n, 0.5)
            ]
            (target / f"{p}.json").write_text(json.dumps({"features": feats}))


def _entry():
    return {
        "layer_id": "power_climate",
        "builder": "climatology_rest",
        "source_id": "nasa-power",
        "params": {
            "parameters": {"T2M": "t2m_mean", "PRECTOTCORR": "precip_annual"},
            "unit_conversions": {"precip_annual": {"factor": 365.25}},
        },
        "resampling": "bilinear",
        "outputs": [
            {"layer_id": "t2m_mean", "quantity": "t2m_mean", "unit": "degC", "statistic": "mean"},
            {"layer_id": "precip_annual", "quantity": "p", "unit": "mm/yr", "statistic": "sum"},
        ],
    }


def test_build_fills_land_converts_and_caches(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    land = np.zeros((cells.N_ROWS, cells.N_COLS), dtype="float32")
    land[1000:1100, 2000:2100] = 1.0
    cells.write_layer(stage / "land_mask.tif", land)
    src = FakeSource(tmp_path / "cache")
    ctx = SimpleNamespace(
        stage_dir=stage, sources=SimpleNamespace(get=lambda _id: src), settings={}
    )
    layers = cr.ClimatologyRestBuilder().build(_entry(), ctx)
    assert [layer["layer_id"] for layer in layers] == ["t2m_mean", "precip_annual"]
    first = src.downloads
    assert first > 0
    precip = cells.read_layer(stage / "precip_annual.tif")
    assert np.isfinite(precip[land > 0]).all()
    assert precip[1050, 2050] == pytest.approx(2.0 * 365.25, rel=1e-4)
    cr.ClimatologyRestBuilder().build(_entry(), ctx)
    assert src.downloads == first  # second build: zero requests


def test_config_errors(tmp_path):
    bad = _entry()
    bad["outputs"] = bad["outputs"][:1]
    ctx = SimpleNamespace(stage_dir=tmp_path, sources=SimpleNamespace(get=lambda _i: None))
    with pytest.raises(ConfigError):
        cr.ClimatologyRestBuilder().build(bad, ctx)
    with pytest.raises(SourceError):
        cr.assemble_native([])
