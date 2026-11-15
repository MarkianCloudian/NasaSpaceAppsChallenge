"""Online checks for T050/T072 (skipped by default; run with `pytest -m online`)."""
import pytest

from analogfinder.config import load_mineral_classes
from analogfinder.planetary.crism import ode_search
from analogfinder.refine.mineralogy import refine_area
from analogfinder.sources.earthdata import EarthdataSource, login_present

pytestmark = pytest.mark.online

EMIT = {"source_id": "emit-l2b-min", "dataset": "EMIT L2B MIN", "collection": "EMITL2BMIN",
        "dataset_version": "002", "rate_limit": {"requests": 5, "per_seconds": 1}, "retries": 2}
SETTINGS = {"emit": {"min_band_depth": 0.02, "min_cluster_pixels": 4, "max_granules_per_area": 2},
            "coverage": {"min_coverage_fraction": 0.5}}


@pytest.mark.skipif(not login_present(), reason="no Earthdata login")
def test_atacama_has_clay_or_sulfate(tmp_path):
    r = refine_area({"lat": -24.08, "lon": -70.01, "radius_km": 20}, EarthdataSource(EMIT, tmp_path),
                    SETTINGS, load_mineral_classes())
    fr = r["mineral_class_fractions"]
    assert r["state"] == "KNOWN" and (fr["sulfate"] > 0 or fr["al_oh_clay"] > 0 or fr["fe_mg_smectite"] > 0)


def test_ode_finds_jezero_mtrdr():
    obs = ode_search({"lat": 18.44, "lon": 77.45, "radius_km": 20})
    assert obs and all(any(u.endswith(".img") for u in o["files"]) for o in obs)
