"""T035: profiles/mars-rover-jezero.json matches the schema and the data-model v1 criteria."""

from __future__ import annotations

import json

from analogfinder.config import validate_against
from analogfinder.types import Profile
from tests.conftest import ROOT

PROFILE = json.loads((ROOT / "profiles" / "mars-rover-jezero.json").read_text(encoding="utf-8"))
FP_STAT = {
    "hyperarid": "mean",
    "dry_air": "mean",
    "no_vegetation": "p90",
    "barren_ground": "mean",
    "thermal_swing": "mean",
    "regional_slope": "p90",
    "traverse_slope": "p90",
    "roughness": "median",
    "mineral_classes": "mean",
    "aqueous_minerals": "fraction_true",
}
NOT_COMPARABLE = {"pressure", "gravity", "thermal_inertia"}


def test_schema_valid():
    assert validate_against(PROFILE, "profile.schema.json", "mars-rover-jezero.json") == []


def test_identity_and_site():
    p = PROFILE
    assert (p["profile_id"], p["version"], p["body"], p["purpose"]) == (
        "mars-rover-jezero",
        "1.0.0",
        "Mars",
        "rover_expedition",
    )
    site = p["reference_site"]
    assert (site["lat"], site["lon"], site["radius_km"]) == (18.44, 77.45, 20)
    assert p["percentile_population"] == "eligible" and p["min_confidence"] == 0.6
    assert p["search_constraints"]["max_landcover_fraction"] == {
        "urban": 0.1,
        "cropland": 0.2,
        "water": 0.5,
        "snow_ice": 0.5,
    }


def test_exact_criteria_and_footprint_statistics():
    by_id = {c["id"]: c for c in PROFILE["criteria"]}
    assert set(by_id) == set(FP_STAT) | NOT_COMPARABLE
    for cid, stat in FP_STAT.items():
        assert by_id[cid]["footprint_statistic"] == stat, cid
        assert by_id[cid]["comparison"] != "not_comparable"
    for cid in NOT_COMPARABLE:
        assert by_id[cid]["comparison"] == "not_comparable"
    assert all(c["justification"].strip() for c in PROFILE["criteria"])


def test_baselines_and_mineral_fields():
    by_id = {c["id"]: c for c in PROFILE["criteria"]}
    assert by_id["traverse_slope"]["baseline_m"] == 30
    assert by_id["roughness"]["baseline_m"] == 30
    assert by_id["regional_slope"]["baseline_m"] == 926  # = slope_p90_1km layer (D-020)
    m = by_id["mineral_classes"]
    assert m["class_map"] == "config/mineral_classes.json" and m["valid_bands"]
    assert m["target"]["classes"] == ["fe_mg_smectite", "carbonate", "olivine"]


def test_removed_criteria():
    removed = {r["id"]: r["reason"] for r in PROFILE["removed_criteria"]}
    assert set(removed) == {"wind", "landform", "subsurface_feature"}
    assert all(removed.values())


def test_loads_as_profile_type():
    p = Profile.from_frozen_json(PROFILE)
    assert p.ref == "mars-rover-jezero@1.0.0" and len(p.criteria) == 13
    by_id = {c.id: c for c in p.criteria}
    assert by_id["mineral_classes"].earth_sources == ("emit-l2b-min",)
