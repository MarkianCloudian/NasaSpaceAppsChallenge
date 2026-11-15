"""T077: calibration on the synthetic run — a known site at the best blob's best cell ranks 1."""

from __future__ import annotations

import logging
import shutil

from analogfinder import pipeline, stage_io, storage
from analogfinder.calibrate import calibrate
from analogfinder.config import load_settings
from analogfinder.profiles.freeze import freeze
from analogfinder.profiles.load import load_frozen
from analogfinder.types import StageContext
from tests.conftest import ROOT
from tests.fixtures.synthetic_run import mineral_fn, synthetic_hooks, terrain_fn

REF = "mars-rover-jezero@1.0.0"


def test_known_site_in_best_blob_ranks_first(tmp_path):
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", ROOT / "config", prof)
    opts = pipeline.Options(
        config_dir=ROOT / "config", data_dir=tmp_path / "data", profiles_dir=prof
    )
    hooks = synthetic_hooks()
    res = pipeline.run_all(REF, opts, hooks)
    fps = {s["name"]: s["fingerprint"] for s in res.stages}
    sdir = storage.stage_dir(opts.data_dir, "screen", fps["screen"])
    rdir = storage.stage_dir(opts.data_dir, "refine", fps["refine"])
    best = next(c for c in res.results["candidates"] if c["rank"] == 1)
    rep = best["representative"]
    known = {
        "sites": [
            {
                "site_id": "best",
                "name": "at the best cell",
                "lat": rep["lat"],
                "lon": rep["lon"],
                "bodies": ["Mars"],
                "purposes": [],
                "analog_for": "test",
                "reference": "test",
            },
            {
                "site_id": "moon-only",
                "name": "other body",
                "lat": rep["lat"],
                "lon": rep["lon"],
                "bodies": ["Moon"],
                "analog_for": "test",
                "reference": "test",
            },
        ]
    }
    ctx = StageContext(
        stage="calibrate",
        stage_dir=tmp_path / "cal",
        data_dir=opts.data_dir,
        config_dir=opts.config_dir,
        settings=load_settings(opts.config_dir),
        profile=load_frozen(REF, prof),
        grid=hooks.grid(None),
        sources=None,
        log=logging.getLogger("test"),
    )
    rep_ = calibrate(
        res.results,
        stage_io.load_screening(sdir),
        ctx,
        areas=stage_io.load_areas(rdir / "areas.json"),
        known=known,
        terrain_fn=terrain_fn,
        mineral_fn=mineral_fn,
        coverage_fn=lambda fp, c: True,
    )
    assert [s["site_id"] for s in rep_["known_sites"]] == ["best"]  # Moon site not relevant
    site = rep_["known_sites"][0]
    assert site["in_scope"] and site["rejected_by"] is None
    assert site["rank"] == 1 and site["area_id"] == best["area_id"]
    assert site["footprint"] == {"lat": rep["lat"], "lon": rep["lon"], "radius_km": 20}
    assert abs(site["overall_score"] - best["overall_score"]) < 1e-12
    assert not rep_["flag_for_review"] and rep_["flag_reasons"] == []
    assert (tmp_path / "cal" / "calibration.json").exists()
