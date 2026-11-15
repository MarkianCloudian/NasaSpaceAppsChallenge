"""T007 (partial): types build from JSON; the sample-frozen fixture test comes with T034/T035."""

from __future__ import annotations

import dataclasses

import pytest

from tests.fixtures.profiles_inline import criterion, profile


def test_criterion_from_json():
    c = criterion(sources={"target": [], "earth": [{"source_id": "emit-l2b-min"}]})
    assert c.earth_sources == ("emit-l2b-min",) and c.raw["justification"] == "test"
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.id = "x"  # type: ignore[misc]


def test_profile_from_frozen_json():
    p = profile([criterion().raw, criterion("g", comparison="not_comparable").raw], {"c": 1.0})
    assert p.ref == "test@1.0.0" and p.radius_km == 20 and len(p.criteria) == 2
    assert p.percentile_population == "eligible" and p.weights == {"c": 1.0}
