"""gridded_netcdf builder (T043): longitude wrap, Magnus conversion, units, cache."""

from __future__ import annotations

from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from analogfinder.errors import ConfigError
from analogfinder.grid import cells
from analogfinder.grid.builders import gridded_netcdf as gn

LAT = np.array([10.0, 0.0, -10.0])  # descending
LON = np.arange(0.0, 360.0, 90.0)  # 0..270, 0-360 convention
T_K, TD_K = 300.0, 290.0


def _write_nc(path, years=2):
    nt = years * 12
    shape = (nt, len(LAT), len(LON))
    with h5py.File(path, "w") as f:
        f["latitude"] = LAT
        f["longitude"] = LON
        f["valid_time"] = np.arange(nt, dtype="int64")
        lonfield = np.broadcast_to(LON, shape).astype("float32")
        f["t2m"] = np.full(shape, T_K, dtype="float32") + lonfield * 0  # constant
        f["d2m"] = np.full(shape, TD_K, dtype="float32")
        f["tp"] = np.full(shape, 0.001, dtype="float32")  # 1 mm/day
        f["u10"] = np.full(shape, 3.0, dtype="float32")
        f["v10"] = np.full(shape, 4.0, dtype="float32")
        f["ssrd"] = np.full(shape, 3.6e6 * 5, dtype="float32")  # 5 kWh/m2/day
        # month-varying temperature for min/max: replace t2m by 300 + month index
        t = np.zeros(shape, dtype="float32")
        for i in range(nt):
            t[i] = T_K + (i % 12)
        del f["t2m"]
        f["t2m"] = t


def test_magnus_known_value():
    assert gn.magnus_rh(np.array(20.0), np.array(20.0)) == pytest.approx(100.0)
    # T = 20 degC, Td = 10 degC -> about 52.5 % (standard psychrometric value)
    assert gn.magnus_rh(np.array(20.0), np.array(10.0)) == pytest.approx(52.5, abs=0.5)


def test_longitude_wrap_and_latitude_flip():
    data = np.arange(12, dtype="float64").reshape(3, 4)  # (lat, lon)
    lat, lon, out = gn.normalise_grid(LAT, LON, data)
    assert list(lat) == [-10.0, 0.0, 10.0]
    assert list(lon) == [-270.0, -180.0, -90.0, 0.0, 90.0, 180.0]
    # column for lon 270 (= -90) now sits at -90; first row is the southernmost (lat -10)
    i = list(lon).index(-90.0)
    assert out[0, i] == data[2, 3]
    # pad columns repeat the opposite edge
    assert out[0, 0] == out[0, -2] and out[0, -1] == out[0, 1]


def test_bilinear_across_antimeridian():
    # two native columns at lon 170 and -170 (wrapped); the 180° neighbourhood must blend them
    lon = np.array([170.0, 190.0])  # 0-360 style
    data = np.array([[1.0, 3.0], [1.0, 3.0]])
    lat_ax, lon_ax, native = gn.normalise_grid(np.array([0.0, 1.0]), lon, data)
    from analogfinder.grid.builders.climatology_rest import bilinear_to_grid

    out = bilinear_to_grid(lat_ax, lon_ax, native, np.array([0.5]), np.array([179.9, -179.9]))
    assert out[0, 0] == pytest.approx(2.0, abs=0.01) and out[0, 1] == pytest.approx(2.0, abs=0.01)


def test_derived_and_stats():
    m = {
        "t2m": np.full((12, 1, 1), 20.0),
        "d2m": np.full((12, 1, 1), 10.0),
        "u10": np.full((12, 1, 1), 3.0),
        "v10": np.full((12, 1, 1), 4.0),
    }
    assert gn.evaluate_derived("hypot(u10, v10)", m)[0, 0, 0] == pytest.approx(5.0)
    assert gn.evaluate_derived("magnus(t2m, d2m)", m)[0, 0, 0] == pytest.approx(52.5, abs=0.5)
    with pytest.raises(ConfigError):
        gn.evaluate_derived("nope(t2m, d2m)", m)
    rain = np.ones((12, 1, 1))
    assert gn.annual_statistic(rain, "total")[0, 0] == pytest.approx(365.25)


def _entry():
    names = {
        "t2m_mean": ("degC", "annual mean"),
        "t2m_min": ("degC", "annual minimum"),
        "t2m_max": ("degC", "annual maximum"),
        "rh2m_mean": ("percent", "annual mean"),
        "ws10m_mean": ("m/s", "annual mean"),
        "precip_annual": ("mm/yr", "annual total"),
        "insolation_mean": ("kWh/m2/day", "annual mean"),
    }
    return {
        "layer_id": "power_climate",
        "builder": "gridded_netcdf",
        "source_id": "era5-cds",
        "params": {
            "variables": list(gn.VARIABLES),
            "derived": {"rh2m_mean": "magnus(t2m, d2m)", "ws10m_mean": "hypot(u10, v10)"},
            "reference_years": "settings:grid.reference_years",
        },
        "resampling": "bilinear",
        "outputs": [
            {"layer_id": k, "quantity": k, "unit": u, "statistic": s} for k, (u, s) in names.items()
        ],
    }


class FakeSource:
    source_id = "era5-cds"
    entry = {"source_id": "era5-cds", "dataset": "reanalysis-era5-single-levels-monthly-means",
             "dataset_version": "test"}  # fmt: skip

    def __init__(self, root):
        self.root = root
        self.limiter = SimpleNamespace(acquire=lambda: None)

    def cache_path(self, request):
        from analogfinder import storage

        return storage.cache_dir(self.root, self.source_id, "test", request)


def test_build_writes_primary_outputs_and_caches(tmp_path):
    calls = []

    class Client:
        def retrieve(self, dataset, request, target):
            calls.append(request)
            _write_nc(target)

    stage = tmp_path / "stage"
    stage.mkdir()
    ctx = SimpleNamespace(
        stage_dir=stage,
        sources=SimpleNamespace(get=lambda _i: FakeSource(tmp_path / "cache")),
        settings={"grid": {"reference_years": [2020, 2021]}},
    )
    builder = gn.GriddedNetcdfBuilder(client_factory=Client)
    layers = builder.build(_entry(), ctx)
    assert [layer["layer_id"] for layer in layers] == [o["layer_id"] for o in _entry()["outputs"]]
    assert {layer["source_id"] for layer in layers} == {"era5-cds"}  # fallback recorded
    assert calls[0]["year"] == ["2020", "2021"] and len(calls) == 1

    def val(name):
        return float(cells.read_layer(stage / f"{name}.tif")[1800, 3600])

    assert val("t2m_mean") == pytest.approx(T_K - 273.15 + 5.5, abs=1e-3)
    assert val("t2m_min") == pytest.approx(T_K - 273.15, abs=1e-3)
    assert val("t2m_max") == pytest.approx(T_K - 273.15 + 11, abs=1e-3)
    assert val("ws10m_mean") == pytest.approx(5.0, abs=1e-4)
    assert val("precip_annual") == pytest.approx(365.25, abs=1e-2)  # 1 mm/day, m -> mm
    assert val("insolation_mean") == pytest.approx(5.0, abs=1e-4)
    assert 0 < val("rh2m_mean") < 100
    builder.build(_entry(), ctx)
    assert len(calls) == 1  # second build: zero requests


def test_config_errors(tmp_path):
    bad = _entry()
    bad["params"]["variables"] = ["nope"]
    ctx = SimpleNamespace(stage_dir=tmp_path, sources=None, settings={})
    with pytest.raises(ConfigError):
        gn.GriddedNetcdfBuilder().build(bad, ctx)
