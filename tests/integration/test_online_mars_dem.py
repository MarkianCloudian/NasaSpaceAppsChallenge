"""T072 online check for Jezero (skipped by default; run `pytest -m online`)."""

from __future__ import annotations

import json
import math

import pytest

from analogfinder.config import load_sources
from analogfinder.planetary import dem
from tests.conftest import ROOT

pytestmark = pytest.mark.online


def test_jezero_targets(tmp_path):
    profile = json.loads((ROOT / "profiles" / "mars-rover-jezero.json").read_text())
    rows = {r["criterion"]: r for r in dem.extract(profile, load_sources(), data_dir=tmp_path)}
    assert set(rows) == {"regional_slope", "traverse_slope", "roughness"}
    for r in rows.values():
        assert "error" not in r and math.isfinite(r["value"]) and r["coverage"] > 0.5
