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
    st = rep_["stability"]
    assert st["candidates"][0] == {"area_id": best["area_id"], "share_in_top_k": 1.0}


def _fake_results(n: int, profile, seed: int = 1) -> dict:
    import numpy as np

    rng = np.random.default_rng(seed)
    crit = [c for c in profile.criteria if c.comparison != "not_comparable"]
    cands = []
    for i in range(n):
        cands.append(
            {
                "area_id": f"a{i:04d}",
                "status": "ranked",
                "results": [
                    {"criterion_id": c.id, "state": "known", "score": float(rng.uniform(0.6, 1))}
                    for c in crit
                ],
            }
        )
    from analogfinder.scoring.aggregate import aggregate
    from analogfinder.types import CriterionScore

    for c in cands:
        sc = {r["criterion_id"]: CriterionScore(r["score"], 0, 0, "known") for r in c["results"]}
        c["overall_score"] = aggregate(sc, profile).overall
    cands.sort(key=lambda c: (-c["overall_score"], c["area_id"]))
    for i, c in enumerate(cands, 1):
        c["rank"] = i
    return {"candidates": cands}


def test_weight_stability_deterministic_and_fast(tmp_path):
    import time

    from analogfinder.calibrate import weight_stability

    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", ROOT / "config", prof)
    profile = load_frozen(REF, prof)
    cfg = load_settings(ROOT / "config")["stability"]
    results = _fake_results(300, profile)
    t0 = time.monotonic()
    a = weight_stability(results, profile, cfg)
    assert time.monotonic() - t0 < 5.0
    b = weight_stability(results, profile, cfg)
    assert a == b
    assert len(a["candidates"]) == cfg["top_k"]
    assert [c["area_id"] for c in a["candidates"]] == [
        c["area_id"] for c in results["candidates"][: cfg["top_k"]]
    ]
    assert all(0.0 <= c["share_in_top_k"] <= 1.0 for c in a["candidates"])
    other = weight_stability(results, profile, dict(cfg, seed=cfg["seed"] + 1))
    assert other != a
    # range 0: weights unchanged, the baseline top k stays in the top k in every draw
    flat = weight_stability(results, profile, dict(cfg, range=0.0))
    assert all(c["share_in_top_k"] == 1.0 for c in flat["candidates"])


def test_run_writes_calibration_and_about_page_shows_it(tmp_path):
    """T079: `analog run` on the synthetic fixture writes calibration.json; about.html shows it."""
    import json

    from analogfinder.site import build

    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    known = json.loads((cfg / "known_analogs.json").read_text())
    known["sites"].append(
        {
            "site_id": "blob-b",
            "name": "Synthetic blob B",
            "lat": 23.3,
            "lon": 11.5,
            "bodies": ["Mars"],
            "purposes": [],
            "analog_for": "test",
            "reference": "test",
        }
    )
    (cfg / "known_analogs.json").write_text(json.dumps(known))
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", cfg, prof)
    opts = pipeline.Options(config_dir=cfg, data_dir=tmp_path / "data", profiles_dir=prof)
    res = pipeline.run_all(REF, opts, synthetic_hooks())
    assert [s["name"] for s in res.stages][-1] == "calibrate"
    cal_path = opts.data_dir / "runs" / res.run_id / "calibration.json"
    cal = json.loads(cal_path.read_text())
    assert cal == res.calibration
    sites = {s["site_id"]: s for s in cal["known_sites"]}
    assert len(sites) == 10
    assert sites["blob-b"]["in_scope"] and sites["blob-b"]["rank"] is not None
    # the real sites lie outside the small synthetic grid
    assert not sites["atacama-yungay"]["in_scope"]
    assert sites["atacama-yungay"]["out_of_scope_reason"]

    d, _ = build.build_site(opts.data_dir, cfg, prof, res.run_id)
    about = (d / "about.html").read_text()
    assert "Synthetic blob B" in about and "Weight stability" in about
    assert "Calibration was not run" not in about

    again = pipeline.run_all(REF, opts, synthetic_hooks())
    assert again.reused and again.run_id == res.run_id and again.calibration == cal
