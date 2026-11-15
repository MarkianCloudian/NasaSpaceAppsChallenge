"""T012: config/purposes.json is schema-valid and ranks all 8 categories."""

from __future__ import annotations

from analogfinder.config import load_purposes


def test_rover_expedition_ranks():
    p = load_purposes()["purposes"][0]
    assert p["purpose_id"] == "rover_expedition" and p["weight_method"] == "roc"
    assert sorted(p["category_ranks"].values()) == list(range(1, 9))
    assert p["category_ranks"]["operations"] == 1 and p["category_ranks"]["subsurface"] == 8
