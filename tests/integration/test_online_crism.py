"""T073 online check (skipped by default; run `pytest -m online`)."""

from __future__ import annotations

import pytest

from analogfinder.planetary.crism import ode_search

pytestmark = pytest.mark.online


def test_ode_finds_jezero_mtrdr():
    obs = ode_search({"lat": 18.44, "lon": 77.45, "radius_km": 20})
    assert obs and all(any(u.endswith(".img") for u in o["files"]) for o in obs)
