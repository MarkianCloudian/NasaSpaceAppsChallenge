"""modis_cmg builder (T039): QC decoding, scaling, monthly climatology, output recipes."""

from __future__ import annotations

import numpy as np
import pytest
from pyhdf.SD import SD, SDC

from analogfinder.errors import ConfigError
from analogfinder.grid.builders import modis_cmg as m

PARAMS = {
    "variables": {"day": "LST_Day_CMG", "night": "LST_Night_CMG"},
    "scale": 0.02,
    "offset_c": -273.15,
    "qc": {"day": "QC_Day", "night": "QC_Night", "keep": "mandatory_qa_good_or_other_quality"},
}


def _write(path, day, night, qc_day, qc_night):
    sd = SD(str(path), SDC.WRITE | SDC.CREATE)
    for name, arr, typ in (
        ("LST_Day_CMG", day, SDC.UINT16),
        ("LST_Night_CMG", night, SDC.UINT16),
        ("QC_Day", qc_day, SDC.UINT8),
        ("QC_Night", qc_night, SDC.UINT8),
    ):
        s = sd.create(name, typ, arr.shape)
        s[:] = arr
        if typ == SDC.UINT16:
            s.setfillvalue(0)
        s.endaccess()
    sd.end()


def _raw(celsius):
    return np.round((np.asarray(celsius) + 273.15) / 0.02).astype("uint16")


def test_qc_rule_bits():
    qc = np.array([0b00, 0b01, 0b10, 0b11, 0b0100_0001, 0b0100_0010], dtype="uint8")
    keep = m.decode_qc("mandatory_qa_good_or_other_quality", qc)
    assert keep.tolist() == [True, True, False, False, True, False]
    with pytest.raises(ConfigError):
        m.decode_qc("nope", qc)


def test_month_of(tmp_path):
    from pathlib import Path

    assert m.month_of(Path("MOD11C3.A2019001.061.2020.hdf")) == 1
    assert m.month_of(Path("MOD11C3.A2019060.061.2020.hdf")) == 3  # 2019 not a leap year
    assert m.month_of(Path("MOD11C3.A2020336.061.2021.hdf")) == 12


def test_climatology_and_recipes(tmp_path):
    shape = (2, 3)
    files = []
    # two years, January (DOY 001) and July (DOY 182/183)
    spec = [("2019001", 10.0, -10.0), ("2020001", 20.0, -20.0), ("2019182", 50.0, 0.0)]
    for i, (date, d, n) in enumerate(spec):
        day, night = np.full(shape, _raw(d)), np.full(shape, _raw(n))
        qd, qn = np.zeros(shape, "uint8"), np.zeros(shape, "uint8")
        day[0, 0] = 0  # fill value -> invalid
        qn[1, 1] = 0b10  # night rejected by QC
        p = tmp_path / f"MOD11C3.A{date}.061.x{i}.hdf"
        _write(p, day, night, qd, qn)
        files.append(p)
    mc = m.climatology(files, PARAMS)
    assert mc["day"].shape == (12, 2, 3)
    assert mc["day"][0, 1, 1] == pytest.approx(15.0, abs=0.02)  # mean of 10 and 20 degC
    assert mc["day"][6, 1, 1] == pytest.approx(50.0, abs=0.02)
    assert np.isnan(mc["day"][0, 0, 0]) and np.isnan(mc["day"][3, 1, 1])  # fill / no file
    assert np.isnan(mc["night"][0, 1, 1])
    assert mc["night"][0, 0, 1] == pytest.approx(-15.0, abs=0.02)

    assert m.OUTPUT_RECIPES["lst_day_max"][0](mc)[1, 2] == pytest.approx(50.0, abs=0.02)
    assert m.OUTPUT_RECIPES["lst_night_min"][0](mc)[1, 2] == pytest.approx(-15.0, abs=0.02)
    assert m.OUTPUT_RECIPES["lst_amp"][0](mc)[1, 2] == pytest.approx(
        np.mean([30.0, 50.0]), abs=0.05
    )  # (15 - -15) in Jan, (50 - 0) in Jul
    assert m.OUTPUT_RECIPES["lst_mean"][0](mc)[1, 2] == pytest.approx(
        np.mean([0.0, 25.0]), abs=0.05
    )
    assert np.isnan(m.OUTPUT_RECIPES["lst_day_max"][0](mc)[0, 0])  # day fill in every month
    # night rejected by QC in every file at (1, 1) -> no valid month -> NaN
    assert np.isnan(m.OUTPUT_RECIPES["lst_night_min"][0](mc)[1, 1])
    assert not np.isnan(m.OUTPUT_RECIPES["lst_night_min"][0](mc)[1, 2])


def test_resolve_years():
    assert m.resolve_years(
        {"reference_years": "settings:grid.reference_years"},
        {"grid": {"reference_years": [2021, 2019]}},
    ) == [2019, 2021]
    with pytest.raises(ConfigError):
        m.resolve_years({"reference_years": "bogus"}, {})
