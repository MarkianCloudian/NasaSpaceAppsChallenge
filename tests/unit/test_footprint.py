"""T046."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from analogfinder.footprint import _hav_km, _nanquantile, focal, focal_many, kernel_offsets
from analogfinder.types import LandIndex

CELL = 0.05


def land_index(mask: np.ndarray, lat_top: float) -> LandIndex:
    rows, cols = np.nonzero(mask)
    lat = lat_top - (rows + 0.5) * CELL
    lon = -180 + (cols + 0.5) * CELL
    area = (CELL * 111.195) ** 2 * np.cos(np.radians(lat))
    return LandIndex(rows.astype(np.int32), cols.astype(np.int32), lat, lon, area)


def small(lat_top=10.0, rows=60, cols=80, mask=None):
    m = np.ones((rows, cols), bool) if mask is None else mask
    li = land_index(m, lat_top)
    grid = {"lat_top": lat_top, "grid_shape": (rows, cols), "wrap_lon": False}
    return li, grid


def at(li, out, r, c):
    return out[(li.rows == r) & (li.cols == c)][0]


def test_constant_layer_stays_constant():
    li, grid = small()
    z = np.full(li.rows.size, 7.0)
    for stat in ("mean", "median", "max", "min", "p90", "p10"):
        assert np.allclose(focal(z, li, 20, stat, 0.0, **grid), 7.0), stat


def test_single_hot_cell_in_max_only_within_radius():
    li, grid = small()
    hot = int(np.nonzero((li.rows == 30) & (li.cols == 40))[0][0])
    z = np.zeros(li.rows.size)
    z[hot] = 100.0
    out = focal(z, li, 20, "max", 0.0, **grid)
    d = _hav_km(li.lat[hot], li.lat, (li.cols - 40) * CELL)
    # kernel is computed at the 1° band centre: allow a little slack at the edge
    assert (out[d <= 17] == 100).all()
    assert (out[d > 23] == 0).all()


def test_kernel_width_doubles_at_60_degrees():
    def width(lat):
        dr, dc = kernel_offsets(lat, 20, CELL)
        return dc[dr == 0].max() * 2 + 1

    assert width(60.5) / width(0.5) == pytest.approx(2.0, rel=0.15)


def test_fraction_true():
    li, grid = small()
    out = focal((li.cols < 40).astype(float), li, 20, "fraction_true", 0.0, **grid)
    assert at(li, out, 30, 0) == 1.0 and at(li, out, 30, 79) == 0.0
    assert 0.3 < at(li, out, 30, 40) < 0.7


def test_min_valid_fraction_coast():
    mask = np.ones((60, 80), bool)
    mask[:, 40:] = False  # sea on the east half
    li, grid = small(mask=mask)
    out = focal(np.ones(li.rows.size), li, 20, "mean", 0.6, **grid)
    assert np.isnan(at(li, out, 30, 39))  # about half the kernel is sea
    assert at(li, out, 30, 10) == 1.0


def test_small_radius_returns_cell_value():
    li, grid = small()
    z = np.arange(li.rows.size, dtype=float)
    assert np.array_equal(focal(z, li, 2.0, "mean", 0.5, **grid), z)


def test_wraps_antimeridian():
    li = land_index(np.ones((20, 7200), bool), 0.5)
    z = np.zeros(li.rows.size)
    z[(li.rows == 10) & (li.cols == 0)] = 5.0  # just east of −180°
    out = focal(z, li, 20, "max", 0.0, lat_top=0.5, grid_shape=(20, 7200))
    assert at(li, out, 10, 7199) == 5.0  # just west of +180°


def test_fast_quantile_matches_numpy():
    rng = np.random.default_rng(1)
    v = rng.random((500, 37))
    v[rng.random(v.shape) < 0.3] = np.nan
    v[0] = np.nan  # all-NaN row
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for q in (0.1, 0.5, 0.9):
            ref = np.nanpercentile(v, q * 100, axis=1)
            assert np.allclose(_nanquantile(v, np.isfinite(v), q), ref, equal_nan=True)


def test_focal_many_equals_single():
    mask = np.ones((60, 80), bool)
    mask[:5, :7] = False
    li, grid = small(lat_top=40.0, mask=mask)
    rng = np.random.default_rng(3)
    a, b = rng.random(li.rows.size), rng.random(li.rows.size)
    many = focal_many({"a": (a, "mean"), "b": (b, "p90")}, li, 20, 0.5, **grid)
    assert np.allclose(many["a"], focal(a, li, 20, "mean", 0.5, **grid), equal_nan=True)
    assert np.allclose(many["b"], focal(b, li, 20, "p90", 0.5, **grid), equal_nan=True)


def test_rejects_non_aligned_vector():
    li, grid = small()
    with pytest.raises(ValueError, match="land-aligned"):
        focal(np.zeros(3), li, 20, "mean", 0.5, **grid)


def test_targets_match_full_pass():
    mask = np.ones((60, 80), bool)
    mask[:, 70:] = False
    li, grid = small(lat_top=40.0, mask=mask)
    rng = np.random.default_rng(5)
    a = rng.random(li.rows.size)
    full = focal_many({"a": (a, "p90"), "m": (a, "mean")}, li, 20, 0.5, **grid)
    targets = (li.rows >= 20) & (li.rows < 30)
    part = focal_many({"a": (a, "p90"), "m": (a, "mean")}, li, 20, 0.5, targets=targets, **grid)
    for k in ("a", "m"):
        assert np.array_equal(part[k][targets], full[k][targets])  # neighbours from all land
        assert np.isnan(part[k][~targets]).all()
