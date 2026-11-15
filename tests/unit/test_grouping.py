"""T049: candidate areas on the synthetic grid."""

from __future__ import annotations

import logging

import numpy as np

from analogfinder import grouping, screening
from analogfinder.types import StageContext
from tests.conftest import ROOT
from tests.fixtures.synthetic import REGIONS, build_synthetic_grid
from tests.unit.test_scheduler import PROFILE, SETTINGS


def run(tmp_path, settings=SETTINGS):
    g = build_synthetic_grid()
    ctx = StageContext(
        "screen",
        tmp_path,
        tmp_path,
        ROOT / "config",
        settings,
        PROFILE,
        g.as_grid_version(),
        None,
        logging.getLogger("test"),
    )
    scr = screening.run(ctx)
    return grouping.group(scr, ctx), scr, g


def inside(name, lat, lon):
    rs, cs = REGIONS[name]
    lat_top, lon_left = 24.0, 10.0
    r, c = int((lat_top - lat) / 0.05), int((lon - lon_left) / 0.05)
    return rs.start <= r < rs.stop and cs.start <= c < cs.stop


def test_areas_on_synthetic_grid(tmp_path):
    areas, scr, g = run(tmp_path)
    where = {
        a.area_id: [n for n in ("blob_a", "blob_b", "missing_area") if inside(n, *a.representative)]
        for a in areas
    }
    # the two Mars-like blobs, plus the missing-data zone that rank lists as insufficient_data
    assert sorted(sum(where.values(), [])) == ["blob_a", "blob_b", "missing_area"]
    assert len(areas) == 3
    for a in areas:
        assert a.footprint[2] == PROFILE.radius_km
        assert a.area_id == f"mars-rover-jezero-{a.representative[0]:.2f}_{a.representative[1]:.2f}"
        rep = a.rep_idx
        assert scr.screening_score[rep] == np.nanmax(scr.screening_score[a.cell_idx])
        assert a.upper_bound is not None and 0 < a.upper_bound <= 1
        assert set(a.grid_scores) == {c.id for c in screening.grid_criteria(PROFILE)}
        assert a.n_cells == a.cell_idx.size and a.area_km2 > 0


def test_ids_stable_across_runs(tmp_path):
    a1, _, _ = run(tmp_path / "1")
    a2, _, _ = run(tmp_path / "2")
    assert [a.area_id for a in a1] == [a.area_id for a in a2]
    assert [a.upper_bound for a in a1] == [a.upper_bound for a in a2]


def test_large_component_is_split(tmp_path):
    small = {**SETTINGS, "max_area_km2": 30.0 * 4}  # ~4 cells per area
    areas, _, _ = run(tmp_path, small)
    assert len(areas) > 3 and all(a.area_km2 <= 30.9 * 6 for a in areas)


def test_wrap_across_antimeridian():
    n = 7200
    rows = np.array([10, 10], dtype=np.int32)
    cols = np.array([0, n - 1], dtype=np.int32)
    mask = np.zeros((20, n), bool)
    mask[rows, cols] = True
    lab, k = grouping._labels(mask, wrap=True)
    assert k == 1 and lab[10, 0] == lab[10, n - 1]
    assert grouping._labels(mask, wrap=False)[1] == 2


def test_threshold_excludes_low_scores(tmp_path):
    high = {**SETTINGS, "screen_min_score": 0.9999}
    areas, scr, _ = run(tmp_path, high)
    assert all(scr.screening_score[a.rep_idx] >= 0.9999 for a in areas)
