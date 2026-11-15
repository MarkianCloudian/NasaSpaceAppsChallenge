"""Grid orchestration (T044) with fake builders; the fuller integration test is T045."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from analogfinder import cli, config, errors
from analogfinder.grid import build, cells
from analogfinder.types import StageContext

ROOT = Path(__file__).resolve().parents[2]
CALLS: list[str] = []


def _layer(o: dict, entry: dict, name: str) -> dict:
    return {
        "layer_id": o["layer_id"],
        "quantity": o["quantity"],
        "unit": o["unit"],
        "statistic": o["statistic"],
        "source_id": entry["source_id"],
        "dataset_version": "1",
        "resampling": entry["resampling"],
        "file": name,
        "fingerprint": "0" * 16,
    }


class FakeBuilder:
    fail = False

    def build(self, entry, ctx):
        CALLS.append(entry["layer_id"])
        if self.fail and entry["layer_id"] == "fx_terrain":
            raise RuntimeError("source down")
        out = []
        for o in entry["outputs"]:
            cells.write_layer(
                Path(ctx.stage_dir) / f"{o['layer_id']}.tif",
                np.full((cells.N_ROWS, cells.N_COLS), 1.0, dtype="float32"),
            )
            out.append(_layer(o, entry, f"{o['layer_id']}.tif"))
        return out


class FailingBuilder(FakeBuilder):
    fail = True


@pytest.fixture
def setup(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "tests" / "fixtures" / "config", cfg)
    ctx = StageContext(
        stage="grid",
        stage_dir=tmp_path,
        data_dir=tmp_path / "data",
        config_dir=cfg,
        settings=config.load_settings(cfg),
        profile=None,
        grid=None,
        sources=None,  # type: ignore[arg-type]
        log=build.log,
    )
    CALLS.clear()
    return ctx, cfg


def _builders(cls=FakeBuilder):
    return {"climatology_rest": cls, "dem_block_stats": cls}


def _validate(manifest):
    schema = json.loads((ROOT / "schemas" / "grid-manifest.schema.json").read_text())
    errs = list(Draft202012Validator(schema).iter_errors(manifest))
    assert not errs, errs


def test_build_then_reuse(setup):
    ctx, _ = setup
    r1 = build.build_grid(ctx, _builders())
    assert not r1.reused and r1.grid.manifest["status"] == "complete"
    _validate(r1.grid.manifest)
    assert (r1.grid.path / "_COMPLETE").is_file()
    assert "build_seconds" in r1.grid.manifest
    r2 = build.build_grid(ctx, _builders())
    assert r2.reused and r2.grid.grid_id == r1.grid.grid_id
    assert len(CALLS) == 2
    assert r1.grid.layer("precip_annual").shape == (cells.N_ROWS, cells.N_COLS)


def test_changed_layer_reuses_other_files(setup):
    ctx, cfg = setup
    r1 = build.build_grid(ctx, _builders())
    data = json.loads((cfg / "layers.json").read_text())
    data["layers"][1]["params"] = {"block": 2}
    (cfg / "layers.json").write_text(json.dumps(data))
    CALLS.clear()
    r2 = build.build_grid(ctx, _builders())
    assert r2.grid.grid_id != r1.grid.grid_id
    assert CALLS == ["fx_terrain"]  # fx_climate copied
    _validate(r2.grid.manifest)


def test_failing_layer_is_partial_and_retried(setup):
    ctx, _ = setup
    r1 = build.build_grid(ctx, _builders(FailingBuilder))
    m = r1.grid.manifest
    assert m["status"] == "partial"
    assert m["missing_layers"][0]["layer_id"] == "slope_p90_1km"
    assert "source down" in m["missing_layers"][0]["reason"]
    assert [x["layer_id"] for x in m["layers"]] == ["precip_annual"]
    _validate(m)
    CALLS.clear()
    r2 = build.build_grid(ctx, _builders())
    assert not r2.reused and r2.grid.grid_id == r1.grid.grid_id
    assert r2.grid.manifest["status"] == "complete"
    assert CALLS == ["fx_terrain"]
    assert len(list((ctx.data_dir / "grids").iterdir())) == 1


def test_unknown_builder(setup):
    ctx, cfg = setup
    data = json.loads((cfg / "layers.json").read_text())
    data["layers"][0]["builder"] = "nope"
    (cfg / "layers.json").write_text(json.dumps(data))
    with pytest.raises(errors.ConfigError):
        build.build_grid(ctx, _builders())


def test_status_report_and_cli(setup, capsys):
    ctx, cfg = setup
    build.build_grid(ctx, _builders())
    rep = build.status_report(ctx.data_dir)
    assert rep["grids"][0]["complete"] and rep["grids"][0]["layers"] == 2
    code = cli.main(["--config-dir", str(cfg), "--data-dir", str(ctx.data_dir), "status"])
    assert code == 0 and "complete" in capsys.readouterr().out
