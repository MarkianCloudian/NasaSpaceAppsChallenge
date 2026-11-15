"""T080: known-site calibration (T077) and weight stability (T078) on the synthetic grid."""

from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np
import pytest

from analogfinder import screening
from analogfinder.calibrate import calibrate, conservative_rank, in_top, weight_stability
from analogfinder.types import CandidateArea, StageContext
from tests.conftest import ROOT
from tests.fixtures.synthetic import CELL, LAT_TOP, LON_LEFT, build_synthetic_grid
from tests.fixtures.synthetic_run import mineral_fn, terrain_fn
from tests.unit.test_scheduler import PROFILE, SETTINGS


def cell_centre(r: int, c: int) -> tuple[float, float]:
    return LAT_TOP - (r + 0.5) * CELL, LON_LEFT + (c + 0.5) * CELL


BLOB_B = cell_centre(14, 30)  # inside blob_b (Mars-like, driest)
VETO = cell_centre(5, 18)  # centre of veto_area (dense vegetation)


def site(sid, lat, lon, bodies=("Mars",), purposes=()):
    return {
        "site_id": sid,
        "name": sid,
        "lat": lat,
        "lon": lon,
        "bodies": list(bodies),
        "purposes": list(purposes),
        "analog_for": "test",
        "reference": "test",
    }


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("cal")
    ctx = StageContext(
        "calibrate",
        d,
        d,
        ROOT / "config",
        SETTINGS,
        PROFILE,
        build_synthetic_grid().as_grid_version(),
        None,
        logging.getLogger("test"),
    )
    scr = screening.run(replace(ctx, stage="screen", stage_dir=d / "screen"))
    return ctx, scr


def run(env, known_sites, results=None, profile=None, **kw):
    ctx, scr = env
    if profile is not None:
        ctx = replace(ctx, profile=profile)
    kw.setdefault("terrain_fn", terrain_fn)
    return calibrate(
        results or {"candidates": []},
        scr,
        ctx,
        known={"sites": known_sites},
        mineral_fn=mineral_fn,
        coverage_fn=lambda fp, c: True,
        write=False,
        **kw,
    )


def ranked(aid, score, rank):
    return {
        "area_id": aid,
        "status": "ranked",
        "rank": rank,
        "overall_score": score,
        "refinement_level": "full",
        "upper_bound": score,
        "bbox": [0.0, 0.0, 0.0, 0.0],
        "n_cells": 1,
        "results": [],
    }


def unrefined(aid, bound, level="none"):
    return {
        "area_id": aid,
        "status": "screened_only",
        "rank": None,
        "overall_score": None,
        "refinement_level": level,
        "upper_bound": bound,
        "bbox": [0.0, 0.0, 0.0, 0.0],
        "n_cells": 1,
        "results": [],
    }


def site_score(env, s) -> float:
    rec = run(env, [s])["known_sites"][0]
    assert rec["overall_score"] is not None
    return rec["overall_score"]


def test_known_site_inside_top_area_rank_1_no_flag(env):
    s = site("top", *BLOB_B)
    sc = site_score(env, s)
    results = {
        "candidates": [ranked("top-area", sc, 1)]
        + [ranked(f"lower-{i}", sc * (0.9 - 0.1 * i), i + 2) for i in range(4)]
    }
    rep = run(env, [s], results)
    k = rep["known_sites"][0]
    assert k["in_scope"] and k["rejected_by"] is None
    assert k["rank"] == 1 and k["percentile_rank"] == pytest.approx(1 / 5)
    assert not rep["flag_for_review"] and rep["flag_reasons"] == []


def test_conservative_rank_counts_unrefined_bounds_above_site(env):
    s = site("top", *BLOB_B)
    sc = site_score(env, s)
    results = {
        "candidates": [
            ranked("lower", sc - 0.1, 1),
            unrefined("bound-above", sc + 0.01, level="terrain"),
            unrefined("bound-below", sc - 0.01),
        ]
    }
    k = run(env, [s], results)["known_sites"][0]
    assert k["rank"] == 2  # only the unrefined area whose bound exceeds the site counts
    assert k["percentile_rank"] == pytest.approx(2 / 3)
    assert conservative_rank(sc, results["candidates"]) == 2


def test_vetoed_site_reported_with_score_and_flag(env):
    s = site("veto", *VETO)
    top = site("top", *BLOB_B)
    sc = site_score(env, top)
    results = {"candidates": [ranked(f"a{i}", sc * (1 - 0.1 * i), i + 1) for i in range(5)]}
    rep = run(env, [s], results)
    k = rep["known_sites"][0]
    assert k["in_scope"]
    assert k["rejected_by"] == "no_vegetation"
    # still scored and ranked (the vegetated circle scores 0, so every area is ahead)
    assert k["overall_score"] is not None and k["limiting_criterion"] is not None
    assert k["rank"] == 1 + sum(
        c["overall_score"] > k["overall_score"] for c in results["candidates"]
    )
    # the only relevant site is vetoed, so none counts for the top 20 %
    assert rep["flag_for_review"] and rep["flag_reasons"] == ["no_known_analog_in_top_20pct"]
    # another relevant site in the top 20 % clears the flag
    rep2 = run(env, [s, top], results)
    assert not rep2["flag_for_review"]


def test_site_15_km_from_best_cell_scored_on_its_own_circle(env):
    ctx, scr = env
    li = scr.land
    lat, lon = BLOB_B[0] + 0.01, BLOB_B[1] - 0.01  # not a cell centre
    i = int(np.flatnonzero((li.rows == 14) & (li.cols == 30))[0])
    best = int(np.flatnonzero((li.rows == 11) & (li.cols == 30))[0])  # 3 rows = ~16.7 km north
    area = CandidateArea(
        area_id="blob-b",
        cell_idx=np.array([best, i]),
        n_cells=2,
        area_km2=50.0,
        bbox=(0, 0, 0, 0),
        centroid=(0, 0),
        representative=(float(li.lat[best]), float(li.lon[best])),
        rep_idx=best,
        footprint=(float(li.lat[best]), float(li.lon[best]), PROFILE.radius_km),
        grid_scores={},
        refined={},
    )
    seen = []

    def spy(a, c):
        seen.append(a.footprint)
        return terrain_fn(a, c)

    k = run(env, [site("off", lat, lon)], areas=[area], terrain_fn=spy)["known_sites"][0]
    assert k["footprint"] == {"lat": lat, "lon": lon, "radius_km": PROFILE.radius_km}
    assert seen == [(lat, lon, PROFILE.radius_km)]
    assert k["cell"] == {"lat": float(li.lat[i]), "lon": float(li.lon[i])}
    assert k["area_id"] == "blob-b"
    # grid-scale values come from the site's own cell, not from the area's best cell
    assert (k["cell"]["lat"], k["cell"]["lon"]) != area.representative


def test_site_outside_search_constraints_not_in_scope(env):
    north_only = replace(PROFILE, search_constraints={"lat_range": [30, 52]})
    rep = run(env, [site("top", *BLOB_B)], profile=north_only)
    k = rep["known_sites"][0]
    assert k["in_scope"] is False and "latitude" in k["out_of_scope_reason"]
    assert k["rank"] is None and k["overall_score"] is None


def test_no_relevant_site_in_scope_flags(env):
    north_only = replace(PROFILE, search_constraints={"lat_range": [30, 52]})
    sites = [
        site("moon", *BLOB_B, bodies=("Moon",)),  # other body: not relevant
        site("other-purpose", *BLOB_B, purposes=("crewed-base",)),  # other purpose
        site("far", -24.08, -70.01),  # no land cell of the grid within the radius
        site("north", *BLOB_B),  # outside the latitude range
    ]
    rep = run(env, sites, profile=north_only)
    assert [k["site_id"] for k in rep["known_sites"]] == ["far", "north"]
    assert not any(k["in_scope"] for k in rep["known_sites"])
    assert "no land cell" in rep["known_sites"][0]["out_of_scope_reason"]
    assert rep["flag_for_review"]
    assert rep["flag_reasons"] == ["no_known_analog_in_scope", "no_known_analog_in_top_20pct"]


def test_site_with_profile_purpose_is_relevant(env):
    rep = run(env, [site("p", *BLOB_B, purposes=(PROFILE.purpose,))])
    assert [k["site_id"] for k in rep["known_sites"]] == ["p"]


def test_in_top_rule():
    assert in_top(2, 10) and not in_top(3, 10)  # percentile_rank <= 0.2
    assert in_top(1, 5) and not in_top(2, 5)
    assert in_top(1, 3) and not in_top(2, 3)  # fewer than 5 areas: rank 1 still counts
    assert not in_top(1, 0)


def _scored_results(n: int, seed: int = 3) -> dict:
    rng = np.random.default_rng(seed)
    crit = [c for c in PROFILE.criteria if c.comparison != "not_comparable"]
    cands = []
    for i in range(n):
        res = [
            {"criterion_id": c.id, "state": "known", "score": float(rng.uniform(0.6, 1))}
            for c in crit
        ]
        res[-1] = {**res[-1], "state": "unknown", "score": None} if i % 3 == 0 else res[-1]
        cands.append(
            {"area_id": f"a{i:03d}", "status": "ranked", "bbox": [0, 0, 0, 0], "results": res}
        )
    for i, c in enumerate(cands, 1):
        c["rank"] = i
    cands.append(
        {"area_id": "rej", "status": "rejected", "rank": None, "bbox": [0, 0, 0, 0], "results": []}
    )
    return {"candidates": cands}


def test_stability_deterministic_and_shares_in_unit_interval():
    cfg = SETTINGS["stability"]
    results = _scored_results(40)
    a = weight_stability(results, PROFILE, cfg)
    assert a == weight_stability(results, PROFILE, cfg)
    assert (a["draws"], a["range"], a["seed"], a["top_k"]) == (
        cfg["draws"],
        cfg["range"],
        cfg["seed"],
        cfg["top_k"],
    )
    assert [c["area_id"] for c in a["candidates"]] == [f"a{i:03d}" for i in range(cfg["top_k"])]
    assert all(0.0 <= c["share_in_top_k"] <= 1.0 for c in a["candidates"])
    assert weight_stability({"candidates": []}, PROFILE, cfg)["candidates"] == []


def test_calibration_report_has_stability(env):
    rep = run(env, [site("top", *BLOB_B)], _scored_results(12))
    assert set(rep["stability"]) == {"draws", "range", "seed", "top_k", "candidates"}
