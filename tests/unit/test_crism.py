"""T072 on a synthetic ENVI summary-parameter file."""
import json

import pytest

from analogfinder.planetary import crism
from tests.conftest import ROOT
from tests.fixtures.minerals_synthetic import CRISM_BANDS, write_crism_su

MC = json.loads((ROOT / "config" / "mineral_classes.json").read_text())


@pytest.fixture
def su(tmp_path):
    return write_crism_su(tmp_path)


def test_band_names(su):
    assert crism.hdr_band_names(su) == CRISM_BANDS
    assert crism.observation_id(su) == "FRT0000ABCD"


def test_full_scene_fractions(su):
    r = crism.class_fractions([su], MC)
    valid = 45 * 50
    assert r["valid_pixels"] == valid
    fr = r["mineral_class_fractions"]
    assert fr["fe_mg_smectite"] == pytest.approx(100 / valid, abs=1e-6)
    assert fr["olivine"] == pytest.approx(25 / valid, abs=1e-6)
    assert fr["sulfate"] == 0 and r["state"] == "KNOWN"


def test_footprint_excludes_corner_block(su):
    # scene centre is (0, 0); 0.8 km radius covers the olivine block (rows/cols 20-24) only
    r = crism.class_fractions([su], MC, {"lat": 0.0, "lon": 0.0, "radius_km": 0.8})
    fr = r["mineral_class_fractions"]
    assert fr["fe_mg_smectite"] == 0 and fr["olivine"] > 0


def test_missing_parameter_is_an_error(tmp_path):
    img = write_crism_su(tmp_path)
    hdr = img.with_suffix(".hdr")
    hdr.write_text(hdr.read_text().replace("SINDEX2", "XXX"))
    with pytest.raises(ValueError, match="SINDEX2"):
        crism.class_fractions([img], MC)
