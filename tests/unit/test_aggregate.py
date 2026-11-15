"""T031."""

from __future__ import annotations

import numpy as np
import pytest

from analogfinder.scoring.aggregate import aggregate, aggregate_arrays, rejected_by_arrays
from analogfinder.types import CriterionScore
from tests.fixtures.profiles_inline import criterion, profile


def cs(s):
    if s is None:
        return CriterionScore(None, None, None, "unknown")
    return CriterionScore(s, 0.0, 0.0, "known")


def prof(weights, vetoes=None, not_comparable=()):
    vetoes = vetoes or {}
    crits = []
    for cid in weights:
        comp = "not_comparable" if cid in not_comparable else "absolute"
        crits.append(criterion(cid, veto=vetoes.get(cid), comparison=comp).raw)
    return profile(crits, {k: v for k, v in weights.items() if k not in not_comparable})


def test_veto_rejects_regardless_of_others():
    p = prof({"a": 0.5, "b": 0.3, "c": 0.2}, {"b": 0.2})
    r = aggregate({"a": cs(1.0), "b": cs(0.1), "c": cs(1.0)}, p)
    assert r.rejected_by == "b" and r.overall is None and r.limiting == "b"


def test_first_veto_in_evaluation_order():
    p = prof({"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.5})
    assert aggregate({"x": cs(0.0), "y": cs(0.0)}, p).rejected_by == "x"


def test_unknown_excluded_and_renormalised():
    # weights 0.5/0.3/0.2, third unknown → exponents 0.625/0.375, C = 0.8
    p = prof({"a": 0.5, "b": 0.3, "c": 0.2})
    r = aggregate({"a": cs(0.8), "b": cs(0.5), "c": cs(None)}, p)
    assert r.confidence == pytest.approx(0.8)
    assert r.overall == pytest.approx(0.8**0.625 * 0.5**0.375)


def test_zero_score_gives_zero():
    p = prof({"a": 0.5, "b": 0.5})
    assert aggregate({"a": cs(0.0), "b": cs(1.0)}, p).overall == 0.0


def test_not_comparable_ignored():
    p = prof({"a": 1.0, "g": 0.0}, not_comparable={"g"})
    nc = CriterionScore(None, None, None, "not_comparable")
    r = aggregate({"a": cs(0.5), "g": nc}, p)
    assert r.overall == pytest.approx(0.5) and r.confidence == 1.0 and r.limiting == "a"


def test_limiting_tie_rule():
    p = prof({"b": 0.2, "a": 0.2, "c": 0.6})
    assert aggregate({k: cs(0.5) for k in "abc"}, p).limiting == "c"  # higher weight first
    p = prof({"b": 0.5, "a": 0.5})
    assert aggregate({k: cs(0.5) for k in "ab"}, p).limiting == "a"  # then id


def test_deterministic():
    p = prof({"a": 0.4, "b": 0.6})
    s = {"a": cs(0.7), "b": cs(0.9)}
    assert aggregate(s, p) == aggregate(dict(reversed(list(s.items()))), p)


def test_arrays_match_scalar():
    p = prof({"a": 0.5, "b": 0.3, "c": 0.2}, {"b": 0.2})
    arr = {
        "a": np.array([0.8, 0.8, 0.0, 0.9]),
        "b": np.array([0.5, 0.5, 1.0, 0.1]),
        "c": np.array([0.3, np.nan, 1.0, 1.0]),
    }
    overall, conf = aggregate_arrays(arr, p)
    rej = rejected_by_arrays(arr, p)
    for j in range(4):
        one = {k: cs(None if np.isnan(v[j]) else float(v[j])) for k, v in arr.items()}
        r = aggregate(one, p)
        assert conf[j] == pytest.approx(r.confidence)
        if r.rejected_by:
            assert rej[j] == "abc".index(r.rejected_by) and np.isnan(overall[j])
        else:
            assert rej[j] == -1 and overall[j] == pytest.approx(r.overall)
