"""T048: screening on the synthetic grid."""

from __future__ import annotations

import json
import logging

import numpy as np
import pytest

from analogfinder import screening
from analogfinder.types import StageContext
from tests.conftest import ROOT
from tests.fixtures.synthetic import REGIONS, build_synthetic_grid
from tests.unit.test_scheduler import PROFILE, SETTINGS


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    d = tmp_path_factory.mktemp("screen")
    g = build_synthetic_grid()
    ctx = StageContext(
        "screen",
        d,
        d,
        ROOT / "config",
        SETTINGS,
        PROFILE,
        g.as_grid_version(),
        None,
        logging.getLogger("test"),
    )
    return screening.run(ctx), g, d


def region_vec(g, li, name):
    rs, cs = REGIONS[name]
    return (li.rows >= rs.start) & (li.rows < rs.stop) & (li.cols >= cs.start) & (li.cols < cs.stop)


def centre(g, li, name):
    rs, cs = REGIONS[name]
    r, c = (rs.start + rs.stop) // 2, (cs.start + cs.stop) // 2
    return int(np.nonzero((li.rows == r) & (li.cols == c))[0][0])


def test_blobs_survive_veto_area_and_background_do_not(result):
    scr, g, _ = result
    li = scr.land
    assert scr.survivors[centre(g, li, "blob_a")] and scr.survivors[centre(g, li, "blob_b")]
    assert not scr.survivors[region_vec(g, li, "veto_area")].any()
    outside = ~(
        region_vec(g, li, "blob_a")
        | region_vec(g, li, "blob_b")
        | region_vec(g, li, "missing_area")
    )
    assert not scr.survivors[outside].any()  # only the Mars-like zones survive
    # the missing-data zone is not vetoed for missing climate: it stays for rank to judge
    # (UNKNOWN criteria, lower confidence, insufficient_data there - T055 scenario 3)
    assert scr.survivors[centre(g, li, "missing_area")]


def test_veto_counts_and_selectivity(result):
    scr, g, _ = result
    by = scr.counts["rejected_by_criterion"]
    assert set(by) == {c.id for c in screening.grid_criteria(PROFILE) if c.veto is not None}
    # barren_ground has no veto since T036 option B; .get keeps the test valid either way
    assert by.get("no_vegetation", 0) + by.get("barren_ground", 0) > 0
    # the first veto applied removes at least as many cells as any later one
    vals = list(by.values())
    assert vals[0] == max(vals)
    n = scr.counts["evaluated_cells"]
    assert n == scr.land.rows.size and scr.counts["survivors"] == int(scr.survivors.sum())


def test_footprint_values_not_raw_values(result):
    scr, g, _ = result
    li = scr.land
    i = centre(g, li, "blob_a")
    raw = g.land_vector("ndvi_max")[i]
    # the footprint p90 near the veto zone differs from the raw cell value somewhere
    diff = np.abs(scr.footprint["no_vegetation"] - g.land_vector("ndvi_max"))
    assert np.nanmax(diff) > 0.1 and raw == pytest.approx(0.05)
    assert set(scr.footprint) == {c.id for c in screening.grid_criteria(PROFILE)}


def test_percentiles_over_eligible_population(result):
    scr, _, d = result
    name, cells = scr.population
    assert name == "eligible" and 0 < cells <= scr.land.rows.size
    assert set(scr.percentiles) == {"hyperarid", "dry_air", "thermal_swing"}
    meta = json.loads((d / "screening.json").read_text())
    assert meta["population"] == ["eligible", cells]


def test_screening_score_nan_where_rejected(result):
    scr, _, _ = result
    assert np.all(np.isnan(scr.screening_score[~scr.survivors]))
    assert np.all(
        (scr.screening_score[scr.survivors] > 0) & (scr.screening_score[scr.survivors] <= 1)
    )


def test_constraint_rejects_by_latitude(tmp_path):
    g = build_synthetic_grid()
    prof = PROFILE.__class__(
        **{
            **{k: getattr(PROFILE, k) for k in PROFILE.__dataclass_fields__},
            "search_constraints": {"lat_range": [-10.0, 23.5]},
        }
    )
    ctx = StageContext(
        "screen",
        tmp_path,
        tmp_path,
        ROOT / "config",
        SETTINGS,
        prof,
        g.as_grid_version(),
        None,
        logging.getLogger("test"),
    )
    scr = screening.run(ctx)
    assert scr.counts["rejected_by_constraint"] == int((scr.land.lat > 23.5).sum()) > 0
