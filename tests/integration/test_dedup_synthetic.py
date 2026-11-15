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
