"""T029: hand-computed cases for every scoring rule."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from analogfinder.crosswalk import Crosswalk
from analogfinder.scoring import rules
from analogfinder.scoring.percentile import Percentile
from tests.conftest import ROOT
from tests.fixtures.profiles_inline import criterion

X = Crosswalk(json.loads((ROOT / "config" / "mineral_classes.json").read_text()))
IDENTITY = Percentile(np.array([0.0, 1.0]), np.array([0.0, 1.0]), 2)  # lookup(x) == x on [0, 1]


def pct_crit(**kw):
    d = {
        "comparison": "normalized",
        "scoring_rule": "percentile",
        "target": {"percentile": 0.0},
        "tolerance": {"percentile": 0.05},
    }
    d.update(kw)
    return criterion("p", **d)


def bool_crit():
    return criterion("b", scoring_rule="boolean", target={"value": True}, tolerance=None)


def test_trapezoid_inside_edges_and_half():
    c = criterion()
    assert rules.score(c, 3.0).score == 1.0
    r = rules.score(c, 9.0)  # exactly one τ_high above max
    assert r.score == 0.0 and r.deviation == 4.0 and r.deviation_ratio == 1.0
    r = rules.score(c, 7.0)  # half τ_high
    assert r.score == pytest.approx(0.5) and r.deviation == 2.0
    assert rules.score(c, -1.0).score == pytest.approx(0.5)  # half τ_low below min
    assert rules.score(c, 20.0).score == 0.0


def test_open_lower_bound_never_penalises():
    c = criterion(target={"min": None, "max": 0.1}, tolerance={"high": 0.05})
    assert rules.score(c, -1e6).score == 1.0
    assert rules.score(c, 0.125).score == pytest.approx(0.5)


def test_sigma_widening():
    assert rules.tau_eff(3, 4) == 5.0
    c = criterion(
        target={"min": 0, "max": 0}, tolerance={"high": 3}, uncertainty={"target_sigma": 4}
    )
    r = rules.score(c, 2.5)  # τ_eff = 5 → 1 − 2.5/5
    assert r.score == pytest.approx(0.5) and r.deviation_ratio == pytest.approx(0.5)
    c2 = criterion(target={"min": 0, "max": 0}, tolerance={"high": 3})
    assert rules.score(c2, 2.5, sigma_e=4.0).score == pytest.approx(0.5)  # σ_earth from caller


def test_hard_bound_without_tolerance():
    c = criterion(tolerance={})
    assert rules.score(c, 5.0).score == 1.0 and rules.score(c, 5.0001).score == 0.0


def test_gaussian():
    c = criterion(scoring_rule="gaussian")
    assert rules.score(c, 2).score == 1.0
    assert rules.score(c, 9).score == pytest.approx(math.exp(-1))


def test_percentile_relative_uses_population():
    r = rules.score(pct_crit(), 0.025, pct=IDENTITY)
    assert r.score == pytest.approx(0.5) and r.relative is True
    assert rules.score(pct_crit(), 0.2, pct=IDENTITY).score == 0.0
    with pytest.raises(ValueError, match="needs the population"):
        rules.score(pct_crit(), 0.1)


def test_boolean():
    assert rules.score(bool_crit(), True).score == 1.0
    assert rules.score(bool_crit(), False).score == 0.0
    assert rules.score(bool_crit(), 0.8).score == 1.0  # fraction_true footprint ≥ 0.5


def test_nan_is_unknown_and_not_comparable():
    for c in (criterion(), bool_crit()):
        r = rules.score(c, float("nan"))
        assert r.state == "unknown" and r.score is None
    assert rules.score(criterion(), None).state == "unknown"
    assert rules.class_overlap(None, ["carbonate"], X).state == "unknown"
    nc = criterion("g", comparison="not_comparable")
    assert rules.score(nc, 3.71).state == "not_comparable"


def test_class_overlap_partial_credit():
    """Hand computation.

    1) target {fe_mg_smectite}, Earth {saponite 0.2}:
       saponite is a species of fe_mg_smectite → credit 1.0.
       presence: num = 1·min(1,1) = 1, den = max(1,1) = 1 → 1.0
       fraction: num = 1·min(1,0.2) = 0.2, den = max(1,0.2) = 1 → 0.2
    2) target {nontronite}, Earth {saponite}: same subgroup, different species → 0.7
    3) target {fe_mg_smectite}, Earth {al_oh_clay}: same group (phyllosilicate) → 0.4
    4) target {fe_mg_smectite, carbonate, olivine}, Earth {fe_mg_smectite, carbonate, al_oh_clay,
       fe_oxide}: matches 1 + 1 + 0 (no mafic) = 2; al_oh_clay is related to fe_mg_smectite (0.4)
       but not its best match → not counted; fe_oxide unrelated to all → +1 in den.
       den = 1 + 1 + 1 + 1 = 4 → 0.5; deviation = 1 class not fully matched.
    """
    co = rules.class_overlap
    assert co({"saponite": 0.2}, ["fe_mg_smectite"], X).score == 1.0
    frac = co({"saponite": 0.2}, ["fe_mg_smectite"], X, mode="fraction")
    assert frac.score == pytest.approx(0.2)
    assert co({"saponite": 1}, ["nontronite"], X).score == pytest.approx(0.7)
    assert co({"al_oh_clay": 1}, ["fe_mg_smectite"], X).score == pytest.approx(0.4)
    earth = {
        "fe_mg_smectite": 0.3,
        "carbonate": 0.1,
        "al_oh_clay": 0.2,
        "fe_oxide": 0.05,
        "olivine": 0.0,
    }
    r = co(earth, ["fe_mg_smectite", "carbonate", "olivine"], X)
    assert r.score == pytest.approx(0.5) and r.deviation == 1.0


def test_class_overlap_via_criterion_class_map():
    c = criterion(
        "mineral_classes",
        scoring_rule="class_overlap",
        target={"classes": ["fe_mg_smectite", "carbonate"]},
        tolerance=None,
        class_map="config/mineral_classes.json",
        valid_bands="2.1-2.5 um",
    )
    assert rules.score(c, {"saponite": 0.1, "calcite": 0.2}).score == 1.0
    assert rules.score(c, float("nan")).state == "unknown"


def test_score_array_equals_scalar():
    c = criterion()
    xs = np.array([-3, -1, 0, 2.5, 5, 7, 9, 12, np.nan])
    s, d = rules.score_array(c, xs)
    for i, x in enumerate(xs):
        one = rules.score(c, float(x))
        if one.score is None:
            assert np.isnan(s[i])
        else:
            assert (s[i], d[i]) == pytest.approx((one.score, one.deviation))
    ps = np.array([0, 0.01, 0.05, 0.5, np.nan])
    sv, _ = rules.score_array(pct_crit(), ps, pct=IDENTITY)
    for i, p in enumerate(ps):
        one = rules.score(pct_crit(), float(p), pct=IDENTITY).score
        assert (np.isnan(sv[i]) and one is None) or sv[i] == pytest.approx(one)
