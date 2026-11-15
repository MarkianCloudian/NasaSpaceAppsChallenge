"""T052: bound-driven refinement schedule (research D-024)."""

from __future__ import annotations

import json
import logging
import random

import numpy as np

from analogfinder.profiles.weights import compute
from analogfinder.refine import scheduler as sch
from analogfinder.scoring.aggregate import aggregate
from analogfinder.types import CandidateArea, CriterionScore, GroupResult, Profile, StageContext
from tests.conftest import ROOT

DRAFT = json.loads((ROOT / "profiles" / "mars-rover-jezero.json").read_text())
PURPOSES = json.loads((ROOT / "config" / "purposes.json").read_text())
W, _ = compute(DRAFT, PURPOSES)
PROFILE = Profile.from_frozen_json({**DRAFT, "weights": W, "content_hash": "x"})
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
GRID_IDS = [
    c.id
    for c in PROFILE.criteria
    if c.evaluation_scale == "grid" and c.comparison != "not_comparable"
]
GROUPS = sch.criterion_groups(PROFILE)
REFINE_IDS = sorted(GROUPS)


def known(s, d=0.0):
    return CriterionScore(s, d, 0.0, "known")


UNKNOWN = CriterionScore(None, None, None, "unknown")


def ctx(**refine):
    s = {**SETTINGS, "refine": {**SETTINGS["refine"], **refine}}
    return StageContext(
        "refine", ROOT, ROOT, ROOT / "config", s, PROFILE, None, None, logging.getLogger("test")
    )


def area(aid, grid_score):
    return CandidateArea(
        area_id=aid,
        cell_idx=np.array([0]),
        n_cells=1,
        area_km2=30.0,
        bbox=(0, 0, 0, 0),
        centroid=(10.0, 10.0),
        representative=(10.0, 10.0),
        rep_idx=0,
        footprint=(10.0, 10.0, 20.0),
        grid_scores={cid: known(grid_score) for cid in GRID_IDS},
        refined={},
    )


def test_groups_from_earth_sources():
    assert GROUPS == {
        "traverse_slope": "terrain",
        "roughness": "terrain",
        "mineral_classes": "mineral",
        "aqueous_minerals": "mineral",
    }


def test_bound_never_below_final_score_property():
    rng = random.Random(42)
    checked = 0
    for case in range(1000):
        measured = {
            cid: (UNKNOWN if rng.random() < 0.15 else known(rng.uniform(0.05, 1)))
            for cid in GRID_IDS
        }
        hint = rng.random() < 0.5
        u_slope = rng.uniform(0.3, 1.0) if hint else 1.0
        estimates = {cid: (u_slope if cid == "traverse_slope" else 1.0) for cid in REFINE_IDS}
        no_emit = rng.random() < 0.3
        impossible = {"mineral"} if no_emit else set()
        bound = sch.upper_bound(measured, estimates, GROUPS, PROFILE, impossible)
        truth = dict(measured)
        for cid in REFINE_IDS:
            group_unknown = GROUPS[cid] == "mineral" and no_emit
            if group_unknown or rng.random() < 0.2:  # whole group or a single criterion unknown
                truth[cid] = UNKNOWN
            else:
                truth[cid] = known(rng.uniform(0.0, estimates[cid]))  # real score <= estimate
        final = aggregate(truth, PROFILE)
        if final.overall is None or final.confidence + 1e-12 < PROFILE.min_confidence:
            continue  # rejected or insufficient data: never ranked
        checked += 1
        assert bound is not None and bound + 1e-12 >= final.overall, (case, bound, final)
    assert checked > 100  # enough rankable cases (others are vetoed or below min_confidence)


def fake_terrain(truth):
    def fn(a, ctx):
        slope, rough = truth[a.area_id]
        return GroupResult(
            "terrain", {"traverse_slope": slope, "roughness": rough}, "nasadem-pc", 1.0
        )

    return fn


def fake_mineral(calls):
    def fn(a, ctx):
        calls.append(a.area_id)
        return GroupResult(
            "mineral",
            {
                "mineral_class_fractions": {"fe_mg_smectite": 0.1, "carbonate": 0.05},
                "aqueous_mineral_present": True,
            },
            "emit-l2b-min",
            0.9,
        )

    return fn


def test_d024_example_mediocre_grid_excellent_terrain_wins():
    a, b = area("A", 0.7), area("B", 0.9)
    truth = {"A": (5.0, 2.0), "B": (21.0, 2.0)}  # A: slope score 1; B: 0.4 (above veto 0.3)
    calls = []
    areas, summary = sch.schedule(
        [b, a],
        ctx(terrain_hint=False),
        fake_terrain(truth),
        fake_mineral(calls),
        lambda fp, c: True,
    )
    s = {x.area_id: x for x in areas}
    assert s["A"].aggregate.overall > s["B"].aggregate.overall
    assert summary["confirmed"][0] == "A"
    assert all(x.upper_bound + 1e-12 >= x.aggregate.overall for x in areas)


def test_no_emit_coverage_finalised_without_emit_pass():
    a = area("C", 0.9)
    calls = []
    areas, _ = sch.schedule(
        [a], ctx(), fake_terrain({"C": (5.0, 2.0)}), fake_mineral(calls), lambda fp, c: False
    )
    assert calls == [] and areas[0].refinement_level == "full"
    assert areas[0].refined["mineral_classes"].state == "unknown"


def test_cap_reached_records_proven_top():
    good = [area(f"G{i}", 0.95) for i in range(2)]
    poor = [area(f"P{i}", 0.55) for i in range(3)]  # above vetoes, bound below the refined ones
    truth = {x.area_id: (5.0, 2.0) for x in good + poor}
    s = {**SETTINGS, "site_top_n": 4}
    c = ctx(max_terrain_areas=2, terrain_hint=False)
    c.settings = {**s, "refine": c.settings["refine"]}
    areas, summary = sch.schedule(
        good + poor, c, fake_terrain(truth), fake_mineral([]), lambda fp, cc: True
    )
    assert summary["stop"] == "cap_reached" and summary["terrain_areas"] == 2
    assert summary["proven_top"] == 2 and set(summary["confirmed"]) == {"G0", "G1"}
    levels = {x.area_id: x.refinement_level for x in areas}
    assert levels == {"G0": "full", "G1": "full", "P0": "none", "P1": "none", "P2": "none"}
    assert summary["emit_covered_areas"] == 2  # no CMR search for areas blocked by the cap


def test_deterministic_order_and_ties():
    def run(order):
        areas = [area(aid, 0.8) for aid in order]
        truth = {aid: (5.0, 2.0) for aid in order}
        _, summary = sch.schedule(
            areas, ctx(), fake_terrain(truth), fake_mineral([]), lambda fp, c: True
        )
        return summary

    r1, r2 = run(["b", "a", "c"]), run(["c", "b", "a"])
    assert r1 == r2 and r1["confirmed"] == ["a", "b", "c"]


def test_vetoed_refinement_score_makes_area_unrankable():
    a = area("V", 0.9)
    areas, summary = sch.schedule(
        [a], ctx(), fake_terrain({"V": (40.0, 2.0)}), fake_mineral([]), lambda fp, c: True
    )
    assert summary["confirmed"] == [] and areas[0].upper_bound == 0.0
