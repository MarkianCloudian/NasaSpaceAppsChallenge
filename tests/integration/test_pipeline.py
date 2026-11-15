"""T054: stage cache, run records and resume (screen/group stubbed until T048/T049 land)."""

from __future__ import annotations

import json
import logging
import shutil
from types import SimpleNamespace

import pytest

from analogfinder import cli, errors, pipeline
from analogfinder.profiles.freeze import freeze
from analogfinder.refine import scheduler
from tests.conftest import ROOT
from tests.unit.test_rank import mineral_fn, screening_and_areas, terrain_fn

GRID = SimpleNamespace(grid_id="0123456789abcdef")


def hooks(fail_refine: list | None = None):
    def screen(ctx):
        return screening_and_areas()[0]

    def group(scr, ctx):
        return screening_and_areas()[1]

    def refine(areas, ctx):
        if fail_refine:
            fail_refine.pop()
            raise RuntimeError("simulated failure during refine")
        return scheduler.schedule(areas, ctx, terrain_fn, mineral_fn, lambda fp, c: True)

    return pipeline.Hooks(
        check=lambda ctx: None,
        grid=lambda ctx: GRID,
        screen=screen,
        group=group,
        refine=refine,
        sources=lambda opts: None,
    )


@pytest.fixture
def opts(tmp_path):
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    freeze(prof / "mars-rover-jezero.json", ROOT / "config", prof)
    return pipeline.Options(
        config_dir=ROOT / "config", data_dir=tmp_path / "data", profiles_dir=prof
    )


REF = "mars-rover-jezero@1.0.0"


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_run_then_reuse_writes_nothing(opts):
    r1 = pipeline.run_all(REF, opts, hooks())
    ranked = [c for c in r1.results["candidates"] if c["status"] == "ranked"]
    assert ranked and ranked[0]["area_id"] == "blob_b" and not r1.reused
    before = files(opts.data_dir)
    r2 = pipeline.run_all(REF, opts, hooks())
    assert r2.reused and r2.run_id == r1.run_id and files(opts.data_dir) == before
    assert r2.results == r1.results


def test_interrupt_in_refine_then_resume(opts, caplog):
    with pytest.raises(RuntimeError, match="simulated failure"):
        pipeline.run_all(REF, opts, hooks(fail_refine=[1]))
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="analogfinder.pipeline"):
        res = pipeline.run_all(REF, opts, hooks())
    text = caplog.text
    assert "check: skipped" in text and "grid: 0123456789abcdef" in text
    assert "screen: reused" in text and "refine: computed" in text and "rank: computed" in text
    assert res.results is not None


def test_run_directory_and_index(opts):
    res = pipeline.run_all(REF, opts, hooks())
    rdir = opts.data_dir / "runs" / res.run_id
    assert (rdir / "site" / "index.html").exists()  # T066
    assert {f for f in files(rdir) if not f.startswith("site/")} == {
        "_COMPLETE",
        "run_record.json",
        "results.json",
        "results.csv",
        "calibration.json",
        "results.dedup.json",
    }
    rec = json.loads((rdir / "run_record.json").read_text())
    assert rec["run_id"] == res.run_id == res.results["run_record"]["run_id"]
    assert set(rec["stage_fingerprints"]) == {
        "grid",
        "screen",
        "refine",
        "rank",
        "calibrate",
        "dedup",
    }
    index = json.loads((opts.data_dir / "runs" / "index.json").read_text())
    assert [r["run_id"] for r in index[REF]] == [res.run_id]
    assert pipeline.resolve_ref(opts.data_dir, latest=True) == REF
    assert pipeline.resolve_ref(opts.data_dir, run=res.run_id) == REF
    # results in the run dir are links/copies of the rank stage files
    kfp = rec["stage_fingerprints"]["rank"]
    stage = opts.data_dir / "stages" / "rank" / kfp / "results.json"
    assert (rdir / "results.json").read_bytes() == stage.read_bytes()


def test_skip_refine_is_a_screening_preview(opts):
    res = pipeline.run_all(REF, pipeline.Options(**{**opts.__dict__, "skip_refine": True}), hooks())
    c = res.results["candidates"]
    assert all(x["status"] in ("screened_only", "rejected") for x in c)
    assert not any(x["status"] == "ranked" for x in c)
    assert all(x["upper_bound"] is not None for x in c if x["status"] == "screened_only")
    assert res.results["run_record"]["refinement"]["stop"] == "skipped"
    assert res.exit_code == errors.NO_CANDIDATES
    st = {s["name"]: s["status"] for s in res.stages}
    assert st["calibrate"] == st["dedup"] == "skipped"  # D-025
    assert res.calibration is None
    assert not (opts.data_dir / "runs" / res.run_id / "calibration.json").exists()


def test_overrides_change_refine_fingerprint_only(opts):
    a = pipeline.run_all(REF, opts, hooks())
    b = pipeline.run_all(
        REF, pipeline.Options(**{**opts.__dict__, "max_terrain_areas": 1}), hooks()
    )
    sa = {s["name"]: s for s in a.stages}
    sb = {s["name"]: s for s in b.stages}
    assert (
        sb["screen"]["status"] == "reused"
        and sb["screen"]["fingerprint"] == sa["screen"]["fingerprint"]
    )
    assert sb["refine"]["fingerprint"] != sa["refine"]["fingerprint"] and a.run_id != b.run_id


def test_refuses_drafts(opts):
    with pytest.raises(errors.ValidationError, match="not frozen"):
        pipeline.run_all("mars-rover-jezero@2.0.0", opts, hooks())


def test_cli_run_and_stage_commands(opts, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "DEFAULT_HOOKS", hooks())
    base = ["--config-dir", str(opts.config_dir), "--data-dir", str(opts.data_dir)]
    pdir = ["--profiles-dir", str(opts.profiles_dir)]
    assert cli.main(base + ["run", "--profile", REF] + pdir) == 0
    run_id = capsys.readouterr().out.split()[1]
    assert cli.main(base + ["run", "--latest"] + pdir) == 0
    assert capsys.readouterr().out.startswith(f"reused {run_id}")
    assert cli.main(base + ["screen", "--run", run_id] + pdir) == 0
    assert "run: " in capsys.readouterr().out
