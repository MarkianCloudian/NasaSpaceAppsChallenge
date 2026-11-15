"""Regenerate the site fixtures (task T058) from an offline synthetic pipeline run.

    uv run python -m tests.fixtures.make_site_fixtures

Writes `tests/fixtures/results_sample.json` (5 candidates: 3 ranked from the synthetic run, one
`insufficient_data` with UNKNOWN terrain criteria, one `rejected` by a veto; relative and
not_comparable criteria come from the real Jezero profile; `placeholder_values: true` to exercise
the banner), `tests/fixtures/results_empty.json` (zero candidates) and
`tests/fixtures/site_inputs_sample.json` (the site snapshot for that run). All results files
are validated against `schemas/results.schema.json`.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

from analogfinder import pipeline, stage_io, storage
from analogfinder.profiles.freeze import freeze
from analogfinder.site.build import collect_inputs
from tests.fixtures.synthetic import build_synthetic_grid
from tests.fixtures.synthetic_run import synthetic_hooks

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
REF = "mars-rover-jezero@1.0.0"


def _move(c: dict, lat: float, lon: float, pid: str) -> None:
    c["area_id"] = f"{pid}-{lat:.2f}_{lon:.2f}"
    for k in ("representative", "centroid"):
        c[k] = {**c[k], "lat": lat, "lon": lon}
    c["footprint"] = {**c["footprint"], "lat": lat, "lon": lon}


def make() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        prof = tmp / "profiles"
        prof.mkdir()
        shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
        freeze(prof / "mars-rover-jezero.json", ROOT / "config", prof)
        opts = pipeline.Options(
            config_dir=ROOT / "config", data_dir=tmp / "data", profiles_dir=prof
        )
        res = pipeline.run_all(REF, opts, synthetic_hooks()).results
        grid = build_synthetic_grid().as_grid_version()
        gdir = storage.grid_dir(tmp / "data", res["run_record"]["grid_id"])
        gdir.mkdir(parents=True)
        stage_io.write_json(gdir / "manifest.json", grid.manifest)
        inputs = collect_inputs(res, tmp / "data", ROOT / "config", prof)

    pid = res["run_record"]["profile"]["id"]
    base = res["candidates"][-1]
    ins = copy.deepcopy(base)
    _move(ins, -24.10, -69.95, pid)
    ins.update(status="insufficient_data", rank=None, overall_score=None, confidence=0.42,
               limiting_criterion=None, refinement_level="none")  # fmt: skip
    for r in ins["results"]:
        if r["criterion_id"] in (
            "traverse_slope",
            "roughness",
            "mineral_classes",
            "aqueous_minerals",
        ):
            r.update(
                state="unknown",
                earth_value=None,
                score=None,
                deviation=None,
                deviation_ratio=None,
                weight_effective=None,
                note="no DEM / EMIT coverage",
            )
    rej = copy.deepcopy(base)
    _move(rej, 30.50, 31.20, pid)
    rej.update(status="rejected", rank=None, overall_score=None, rejected_by="no_vegetation",
               limiting_criterion="no_vegetation")  # fmt: skip
    for r in rej["results"]:
        if r["criterion_id"] == "no_vegetation":
            r.update(earth_value=0.31, deviation=0.16, deviation_ratio=1.6, score=0.0)
    sample = copy.deepcopy(res)
    sample["candidates"] = res["candidates"] + [ins, rej]
    rr = sample["run_record"]
    rr["placeholder_values"] = True
    rr["counts"] = {**rr["counts"], "areas": 5, "insufficient_data": 1}

    empty = copy.deepcopy(res)
    empty["candidates"] = []
    empty["run_record"]["counts"] = {**res["run_record"]["counts"], "areas": 0, "refined": 0,
                                     "ranked": 0}  # fmt: skip

    schema = json.loads((ROOT / "schemas" / "results.schema.json").read_text())
    for name, doc in (("results_sample.json", sample), ("results_empty.json", empty)):
        errs = sorted(Draft202012Validator(schema).iter_errors(doc), key=str)
        if errs:
            raise SystemExit(f"{name}: {errs[0].message} at {list(errs[0].path)}")
        stage_io.write_json(OUT / name, doc)
    stage_io.write_json(OUT / "site_inputs_sample.json", inputs)
    print("wrote results_sample.json, results_empty.json, site_inputs_sample.json")


if __name__ == "__main__":
    make()
