"""Full offline run on the synthetic grid with the real screening (T048) and grouping (T049)."""

from __future__ import annotations

import shutil

import pytest

from analogfinder import pipeline
from analogfinder.profiles.freeze import freeze
from tests.conftest import ROOT
from tests.fixtures.synthetic_run import synthetic_hooks

REF = "mars-rover-jezero@1.0.0"


@pytest.fixture
def opts(tmp_path):
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", ROOT / "config", prof)
    return pipeline.Options(
        config_dir=ROOT / "config", data_dir=tmp_path / "data", profiles_dir=prof
    )


def test_real_screening_and_grouping_end_to_end(opts):
    res = pipeline.run_all(REF, opts, synthetic_hooks())
    cands = res.results["candidates"]
    ranked = [c for c in cands if c["status"] == "ranked"]
    assert ranked and ranked[0]["rank"] == 1
    # the drier blob (rows 11-17, cols 26-35 -> lat ~23.2-23.4, lon ~11.3-11.8) ranks first
    top = ranked[0]["representative"]
    assert 23.1 < top["lat"] < 23.5 and 11.25 < top["lon"] < 11.85
    assert all(c["footprint"]["radius_km"] == 20 for c in cands)
    again = pipeline.run_all(REF, opts, synthetic_hooks())
    assert again.reused and again.run_id == res.run_id


def test_run_links_site_into_run_directory(opts):
    """T066: `analog run` on the synthetic fixture writes data/runs/<run_id>/site/index.html."""
    import json

    res = pipeline.run_all(REF, opts, synthetic_hooks())
    site = opts.data_dir / "runs" / res.run_id / "site"
    assert (site / "index.html").exists() and (site / "about.html").exists()
    marker = json.loads((site / "_COMPLETE").read_text())  # the site stage's own marker
    stage = {s["name"]: s for s in res.stages}["site"]
    assert marker["fingerprint"] == stage["fingerprint"] and marker["run_id"] == res.run_id
    cache = opts.data_dir / "stages" / "site" / stage["fingerprint"] / "index.html"
    assert cache.read_bytes() == (site / "index.html").read_bytes()
    assert (site / "index.html").stat().st_ino == cache.stat().st_ino  # hard link, not a copy
    again = pipeline.run_all(REF, opts, synthetic_hooks())
    assert {s["name"]: s["status"] for s in again.stages}["site"] == "reused"
    # stages run on their own (`analog rank`) render no site
    part = pipeline.run_all(
        REF, pipeline.Options(**{**opts.__dict__, "until": "rank"}), synthetic_hooks()
    )
    assert not (opts.data_dir / "runs" / part.run_id / "site").exists()
