"""T033."""

from __future__ import annotations

import numpy as np
import pytest

from analogfinder.scoring.percentile import Percentile, load, population_mask, save


def cos_w(lats):
    return np.cos(np.radians(np.asarray(lats, dtype=float)))


def test_min_max_and_uniform():
    v = np.arange(100, dtype=float)
    t = Percentile.build(v, np.ones_like(v))
    assert t.lookup(0.0) == 0.0 and t.lookup(99.0) == 1.0
    assert t.lookup(49.5) == pytest.approx(0.5)
    assert t.lookup(-5) == 0.0 and t.lookup(500) == 1.0 and np.isnan(t.lookup(np.nan))


def test_area_weighting_by_hand():
    """Values 10 @ 60° (w 0.5), 20 @ 0° (w 1), 30 @ 0° (w 1).
    mid-points: 0.25, 1.0, 2.0 → p(20) = (1.0 − 0.25)/(2.0 − 0.25) = 3/7.
    Without area weighting p(20) would be 0.5."""
    v = np.array([10.0, 20.0, 30.0])
    t = Percentile.build(v, cos_w([60.0, 0.0, 0.0]))
    assert t.lookup(20.0) == pytest.approx(3 / 7)
    assert Percentile.build(v, np.ones(3)).lookup(20.0) == pytest.approx(0.5)


def test_ice_region_populations():
    # cells 0-3: ice sheet, lowest precipitation; 4-7: desert (lowest non-ice); rest wetter
    v = np.array([0.0, 1, 2, 3, 5, 6, 7, 8, 20, 30, 40, 50, 60, 70, 80, 90])
    w = np.ones_like(v)
    land = np.ones_like(v, bool)
    snow = np.zeros_like(v)
    snow[:4] = 0.9
    constraints = snow < 0.5  # hard constraint: no snow/ice
    desert = 5.0
    p = {}
    for name in ("eligible", "ice_free_land", "all_land"):
        m = population_mask(name, land, constraints_mask=constraints, snow_ice_footprint=snow)
        p[name] = float(Percentile.build(v[m], w[m]).lookup(desert))
    assert p["eligible"] == pytest.approx(0.0) and p["ice_free_land"] == pytest.approx(0.0)
    assert p["all_land"] > 0.2


def test_round_trip(tmp_path):
    t = Percentile.build(np.array([1.0, 2.0, np.nan]), cos_w([10, 10, 10]))
    assert t.n_cells == 2
    save(t, tmp_path, "dry_air")
    t2 = load(tmp_path, "dry_air")
    assert t2.lookup(1.5) == t.lookup(1.5)


def test_unknown_population():
    with pytest.raises(ValueError, match="unknown percentile population"):
        population_mask("everything", np.ones(3, bool))
