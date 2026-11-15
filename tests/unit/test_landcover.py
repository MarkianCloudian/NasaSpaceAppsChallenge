"""`landcover_fractions` builder (T038): class-group fractions and land rule on tiny HDF4 files."""

from __future__ import annotations

import numpy as np
import pytest
from pyhdf.SD import SD, SDC

from analogfinder.errors import ConfigError
from analogfinder.grid.builders import landcover_fractions as lc

GROUPS = {"water": [0], "forest": [1, 2], "barren": [16]}
SHAPE = (2, 3)


def _write(path, pct, axis=2):
    """pct: (rows, cols, 17) uint8 percentages; stored with the class axis last or first."""
    arr = pct if axis == 2 else np.moveaxis(pct, 2, 0)
    sd = SD(str(path), SDC.WRITE | SDC.CREATE)
    s = sd.create("Land_Cover_Type_1_Percent", SDC.UINT8, arr.shape)
    s[:] = np.ascontiguousarray(arr)
    s.setfillvalue(255)
    s.endaccess()
    sd.end()
    return path


def _pct():
    p = np.zeros(SHAPE + (17,), dtype="uint8")
    p[0, 0, 0] = 100  # ocean
    p[0, 1, 16] = 90  # desert with a little water
    p[0, 1, 0] = 10
    p[0, 2, 1], p[0, 2, 2] = 30, 30  # forest 60 %, water 40 %
    p[0, 2, 0] = 40
    p[1, 0, 0], p[1, 0, 16] = 50, 50  # half water
    p[1, 1, :] = 255  # missing
    p[1, 2, 10] = 100  # grassland (no group)
    return p


@pytest.mark.parametrize("axis", [2, 0])
def test_fractions(tmp_path, axis):
    f = _write(tmp_path / f"MCD12C1.A2023001.{axis}.hdf", _pct(), axis)
    fr = lc.read_fractions(f, "Land_Cover_Type_1_Percent", GROUPS, 0.01, grid_dims=SHAPE)
    assert fr["water"][0, 0] == pytest.approx(1.0)
    assert fr["barren"][0, 1] == pytest.approx(0.9)
    assert fr["forest"][0, 2] == pytest.approx(0.6)
    assert fr["water"][1, 2] == 0.0 and fr["barren"][1, 2] == 0.0
    assert all(np.isnan(fr[g][1, 1]) for g in GROUPS)


def test_land_rule():
    g, cmp, t = lc.parse_land_rule("water < 0.5", GROUPS)
    assert g == "water" and t == 0.5
    water = np.array([1.0, 0.1, 0.5, np.nan])
    land = np.where(np.isfinite(water), cmp(water, t), False)
    assert land.tolist() == [False, True, False, False]
    with pytest.raises(ConfigError):
        lc.parse_land_rule("ice < 0.5", GROUPS)
    with pytest.raises(ConfigError):
        lc.parse_land_rule("water ~ 0.5", GROUPS)


def test_class_beyond_sds_rejected(tmp_path):
    f = _write(tmp_path / "x.hdf", _pct())
    with pytest.raises(ConfigError, match="class 20"):
        lc.read_fractions(f, "Land_Cover_Type_1_Percent", {"x": [20]}, 0.01, grid_dims=SHAPE)


def test_resolve_year():
    assert lc.resolve_year({"year": 2023}, {}) == 2023
    s = {"grid": {"reference_years": [2019, 2023, 2021]}}
    assert lc.resolve_year({"year": "settings:grid.reference_years"}, s) == 2023
