"""T025."""

import pytest

from analogfinder.errors import ValidationError
from analogfinder.profiles.weights import compute, compute_for_purpose, roc, roc_ranked

PURPOSE = {
    "purpose_id": "p",
    "weight_method": "roc",
    "category_ranks": {
        "operations": 1,
        "terrain": 2,
        "geology": 3,
        "atmosphere": 4,
        "thermal": 5,
        "resources": 6,
        "biology": 7,
        "subsurface": 8,
    },
}


def crit(cid, cat, rank=1, **kw):
    return {"id": cid, "category": cat, "rank_in_category": rank, "comparison": "absolute", **kw}


def test_roc_n8():
    assert [round(w, 3) for w in roc(8)] == [0.340, 0.215, 0.152, 0.111, 0.079, 0.054, 0.033, 0.016]


def test_tie_at_rank_1_of_3():
    w = roc(3)  # 0.6111, 0.2778, 0.1111
    r = roc_ranked({"a": 1, "b": 1, "c": 3})
    assert r["a"] == pytest.approx((w[0] + w[1]) / 2) and r["b"] == r["a"]
    assert r["c"] == pytest.approx(w[2])


def test_empty_category_dropped_and_sum_one():
    # all 8 categories ranked, profile uses only operations (rank 1) and terrain (rank 2)
    prof = {
        "criteria": [
            crit("a", "operations"),
            crit("b", "terrain"),
            crit("c", "terrain", 2),
            crit("x", "subsurface", comparison="not_comparable"),
        ]
    }
    w, method = compute_for_purpose(prof, PURPOSE)
    assert method == "roc×roc" and "x" not in w
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-12)
    r8 = roc(8)
    W_ops, W_ter = r8[0] / (r8[0] + r8[1]), r8[1] / (r8[0] + r8[1])
    r2 = roc(2)
    assert w["a"] == pytest.approx(W_ops, abs=2e-6)
    assert w["b"] == pytest.approx(W_ter * r2[0], abs=2e-6)
    assert w["c"] == pytest.approx(W_ter * r2[1], abs=2e-6)


def test_direct_sum_wrong_names_profile_and_total():
    prof = {
        "profile_id": "mars-x",
        "version": "1.0.0",
        "criteria": [crit("a", "operations", weight=0.5), crit("b", "terrain", weight=0.4)],
    }
    with pytest.raises(ValidationError, match=r"mars-x@1\.0\.0.*0\.900000"):
        compute_for_purpose(prof, PURPOSE)


def test_direct_ok():
    prof = {"criteria": [crit("a", "operations", weight=0.6), crit("b", "terrain", weight=0.4)]}
    assert compute_for_purpose(prof, PURPOSE) == ({"a": 0.6, "b": 0.4}, "direct")


def test_category_override_rank_and_weight():
    prof = {
        "criteria": [crit("a", "operations"), crit("b", "terrain")],
        "category_overrides": {"terrain": {"rank": 1, "reason": "test"}},
    }
    w, _ = compute_for_purpose(prof, PURPOSE)
    assert w["a"] == pytest.approx(0.5) and w["b"] == pytest.approx(0.5)
    prof["category_overrides"] = {"terrain": {"weight": 0.25, "reason": "test"}}
    w, _ = compute_for_purpose(prof, PURPOSE)
    assert w == {"a": 0.75, "b": 0.25}


def test_rounding_sums_exactly_one():
    prof = {"criteria": [crit(c, "geology", 1) for c in "abc"]}  # three-way tie: 1/3 each
    w, _ = compute_for_purpose(prof, PURPOSE)
    assert sum(w.values()) == 1.0 and all(len(str(v).split(".")[1]) <= 6 for v in w.values())


def test_missing_rank_is_error():
    prof = {"criteria": [{"id": "a", "category": "geology", "comparison": "absolute"}]}
    with pytest.raises(ValidationError, match="rank_in_category missing"):
        compute_for_purpose(prof, PURPOSE)


def test_compute_selects_purpose_from_config():
    purposes = {"purposes": [PURPOSE]}
    prof = {"purpose": "p", "criteria": [crit("a", "operations"), crit("b", "terrain")]}
    assert compute(prof, purposes) == compute_for_purpose(prof, PURPOSE)
    with pytest.raises(ValidationError, match="not found"):
        compute({**prof, "purpose": "landing"}, purposes)
