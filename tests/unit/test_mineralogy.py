"""T050 on a synthetic granule with hand-countable content."""
import json
import math

import pytest

from analogfinder.refine import mineralogy as mn
from analogfinder.sources.base import EmptyResult
from analogfinder.sources.earthdata import EarthdataSource
from tests.conftest import ROOT
from tests.fixtures.minerals_synthetic import EMIT_CENTER, EMIT_STEP, write_emit_granule

MC = json.loads((ROOT / "config" / "mineral_classes.json").read_text())
SETTINGS = {"emit": {"min_band_depth": 0.02, "min_cluster_pixels": 4, "max_granules_per_area": 5},
            "coverage": {"min_coverage_fraction": 0.5}}
FP = {"lat": EMIT_CENTER[0], "lon": EMIT_CENTER[1], "radius_km": 1.5}


def expected_mont_fraction():
    # 10x10 block fully inside the 1.5 km circle; circle area / ortho pixel area
    px = (EMIT_STEP * 111.195) * (EMIT_STEP * 111.195 * math.cos(math.radians(EMIT_CENTER[0])))
    return 100 / (math.pi * FP["radius_km"] ** 2 / px)


@pytest.fixture
def granule(tmp_path):
    return write_emit_granule(tmp_path / "EMIT_L2B_MIN_002_20230101T000000_0000000_000.nc")


def test_fractions(granule):
    r = mn.refine_from_files([granule], FP, SETTINGS, MC)
    fr = r["mineral_class_fractions"]
    assert r["state"] == "KNOWN" and r["coverage_fraction"] == 1.0
    assert fr["fe_mg_smectite"] == pytest.approx(expected_mont_fraction(), rel=0.08)
    assert fr["sulfate"] == pytest.approx(1 - fr["fe_mg_smectite"], abs=1e-6)
    assert fr["carbonate"] == 0          # 2-pixel cluster < min_cluster_pixels
    assert fr["fe_oxide"] == 0           # band depth 0.01 < min_band_depth (also outside circle)
    assert r["aqueous_mineral_present"] is True


def test_low_band_depth_threshold_counts_hematite(granule):
    s = {**SETTINGS, "emit": {**SETTINGS["emit"], "min_band_depth": 0.005}}
    fp = {**FP, "radius_km": 2.2}
    r = mn.refine_from_files([granule], fp, s, MC)
    assert r["state"] == "KNOWN" and r["mineral_class_fractions"]["fe_oxide"] > 0


def test_low_coverage_is_unknown(granule):
    r = mn.refine_from_files([granule], {**FP, "radius_km": 5}, SETTINGS, MC)
    assert r["state"] == "UNKNOWN" and r["mineral_class_fractions"] is None
    assert r["coverage_fraction"] < 0.5


class Dummy:
    source_id = "emit-l2b-min"

    def fetch(self, request):
        raise EmptyResult("none")


def test_outside_latitude_and_no_granule():
    r = mn.refine_area({"lat": 60, "lon": 10, "radius_km": 20}, Dummy(), SETTINGS, MC)
    assert r["state"] == "UNKNOWN" and "52" in r["reason"]
    r = mn.refine_area(FP, Dummy(), SETTINGS, MC)
    assert r["state"] == "UNKNOWN" and "no EMIT granule" in r["reason"]


def test_end_to_end_with_fake_earthdata(tmp_path, granule):
    class API:
        downloads = 0

        def search_data(self, **kw):
            return [{"umm": {"CloudCover": 1}}]

        def download(self, granules, local_path):
            API.downloads += 1
            write_emit_granule(tmp_path / "dl.nc")
            dst = f"{local_path}/{granule.name}"
            (tmp_path / "dl.nc").rename(dst)
            return [dst]

    entry = {"source_id": "emit-l2b-min", "dataset": "EMIT L2B MIN", "collection": "EMITL2BMIN",
             "dataset_version": "002", "rate_limit": {"requests": 10, "per_seconds": 1}, "retries": 0}
    src = EarthdataSource(entry, tmp_path / "data", api=API())
    r1 = mn.refine_area(FP, src, SETTINGS, MC)
    r2 = mn.refine_area(FP, src, SETTINGS, MC)
    assert r1 == r2 and r1["state"] == "KNOWN" and API.downloads == 1
