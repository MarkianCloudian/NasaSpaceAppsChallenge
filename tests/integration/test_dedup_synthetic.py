"""T081: dedup on the synthetic run — a known site at the best area labels it a known analog."""

from __future__ import annotations

import json
import logging
import shutil

from analogfinder import pipeline, stage_io, storage
from analogfinder.config import load_settings
from analogfinder.dedup import dedup
from analogfinder.profiles.freeze import freeze
from analogfinder.profiles.load import load_frozen
from analogfinder.types import StageContext
from tests.conftest import ROOT
from tests.fixtures.synthetic_run import synthetic_hooks

REF = "mars-rover-jezero@1.0.0"


def test_dedup_labels_synthetic_run(tmp_path):
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", ROOT / "config", prof)
    opts = pipeline.Options(
        config_dir=ROOT / "config", data_dir=tmp_path / "data", profiles_dir=prof
    )
    res = pipeline.run_all(REF, opts, synthetic_hooks())
    fps = {s["name"]: s["fingerprint"] for s in res.stages}
    sdir = storage.stage_dir(opts.data_dir, "screen", fps["screen"])
    rdir = storage.stage_dir(opts.data_dir, "refine", fps["refine"])
    best = next(c for c in res.results["candidates"] if c["rank"] == 1)
    rep = best["representative"]
    known = {
        "sites": [
            {
                "site_id": "s",
                "name": "Site at the best area",
                "lat": rep["lat"],
                "lon": rep["lon"] + 0.1,
                "radius_km": 15,
                "bodies": ["Mars"],
                "analog_for": "test",
                "reference": "test",
            }
        ]
    }
    ctx = StageContext(
        "dedup",
        tmp_path / "dd",
        opts.data_dir,
        opts.config_dir,
        load_settings(opts.config_dir),
        load_frozen(REF, prof),
        None,
        None,
        logging.getLogger("test"),
    )
    before = json.dumps(res.results, sort_keys=True)
    out = dedup(
        res.results,
        ctx,
        areas=stage_io.load_areas(rdir / "areas.json"),
        land=stage_io.load_screening(sdir).land,
        known=known,
    )
    assert json.dumps(res.results, sort_keys=True) == before  # input untouched
    assert [c["area_id"] for c in out["candidates"]] == [
        c["area_id"] for c in res.results["candidates"]
    ]
    by = {c["area_id"]: c for c in out["candidates"]}
    assert by[best["area_id"]]["label"] == "known_analog"
    assert by[best["area_id"]]["known_site"] == "Site at the best area"
    assert all(c["label"] in ("known_analog", "new_candidate") for c in out["candidates"])
    rr = out["run_record"]
    assert rr["dedup_applied"] is True
    assert rr["dedup"]["known_analogs"] >= 1 and rr["dedup"]["note"]  # < 3 new on this grid
    on_disk = json.loads((tmp_path / "dd" / "results.dedup.json").read_text())
    assert on_disk == json.loads(json.dumps(out))


def test_run_with_dedup_site_shows_both_sections(tmp_path):
    """T082: `analog run` on the synthetic fixture runs dedup; the site shows new and known."""
    from analogfinder.site import build

    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", cfg, prof)
    opts = pipeline.Options(config_dir=cfg, data_dir=tmp_path / "data", profiles_dir=prof)

    # first run: find the best area, then declare a known analog site there
    first = pipeline.run_all(REF, opts, synthetic_hooks())
    best = next(c for c in first.results["candidates"] if c["rank"] == 1)
    assert sum(c["status"] == "ranked" for c in first.results["candidates"]) >= 2
    known = json.loads((cfg / "known_analogs.json").read_text())
    known["sites"].append(
        {
            "site_id": "best",
            "name": "Synthetic known site",
            "lat": best["representative"]["lat"],
            "lon": best["representative"]["lon"],
            "radius_km": 10,
            "bodies": ["Mars"],
            "analog_for": "test",
            "reference": "test",
        }
    )
    (cfg / "known_analogs.json").write_text(json.dumps(known))

    res = pipeline.run_all(REF, opts, synthetic_hooks())
    st = {s["name"]: s["status"] for s in res.stages}
    assert st["screen"] == st["refine"] == st["rank"] == "reused"
    assert st["calibrate"] == st["dedup"] == "complete"
    rdir = opts.data_dir / "runs" / res.run_id
    dd = json.loads((rdir / "results.dedup.json").read_text())
    assert json.loads((rdir / "results.json").read_text())["run_record"]["dedup_applied"] is False
    assert json.loads((rdir / "run_record.json").read_text())["dedup_applied"] is True
    labels = {c["area_id"]: c["label"] for c in dd["candidates"]}
    assert labels[best["area_id"]] == "known_analog"
    assert "new_candidate" in labels.values()

    d, _ = build.build_site(opts.data_dir, cfg, prof, res.run_id)
    index = (d / "index.html").read_text()
    assert 'id="new"' in index and 'id="known"' in index
    assert "Synthetic known site" in index
    assert "Deduplication not applied" not in index
    assert 'class="known_analog"' in index and 'class="new_candidate"' in index

    # --no-dedup: a different run without labels, the site says dedup was not applied
    nd = pipeline.run_all(
        REF, pipeline.Options(**{**opts.__dict__, "no_dedup": True}), synthetic_hooks()
    )
    assert nd.run_id != res.run_id
    assert {s["name"]: s["status"] for s in nd.stages}["dedup"] == "skipped"
    assert not (opts.data_dir / "runs" / nd.run_id / "results.dedup.json").exists()
    d2, _ = build.build_site(opts.data_dir, cfg, prof, nd.run_id)
    assert "Deduplication not applied" in (d2 / "index.html").read_text()
