"""Grid build end to end with fake layer builders writing the synthetic layers (T045).

Offline: the builders place the synthetic grid (T034) into the top-left corner of the fixed
full-size grid; nothing is downloaded.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from analogfinder import config
from analogfinder.grid import build, cells
from analogfinder.types import StageContext
from tests.fixtures.synthetic import build_synthetic_grid

ROOT = Path(__file__).resolve().parents[2]
SYNTH = build_synthetic_grid()
CALLS: list[str] = []


class SyntheticBuilder:
    """Writes the synthetic layer named by each output (or NaN if the synthetic grid lacks it)."""

    failing: frozenset[str] = frozenset()

    def build(self, entry, ctx):
        CALLS.append(entry["layer_id"])
        if entry["layer_id"] in self.failing:
            raise RuntimeError("synthetic source down")
        out = []
        for o in entry["outputs"]:
            full = np.full((cells.N_ROWS, cells.N_COLS), np.nan, dtype="float32")
            src = SYNTH.layers.get(o["layer_id"])
            if src is not None:
                full[: src.shape[0], : src.shape[1]] = src
            name = f"{o['layer_id']}.tif"
            cells.write_layer(Path(ctx.stage_dir) / name, full)
            out.append(
                {
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
            )
        return out


class FailingTerrainBuilder(SyntheticBuilder):
    failing = frozenset({"fx_terrain"})


def _builders(cls=SyntheticBuilder):
    return {"climatology_rest": cls, "dem_block_stats": cls}


@pytest.fixture
def env(tmp_path):
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


def _assert_schema_valid(manifest) -> None:
    schema = json.loads((ROOT / "schemas" / "grid-manifest.schema.json").read_text())
    errors = list(Draft202012Validator(schema).iter_errors(manifest))
    assert not errors, errors


def _grid_dirs(ctx) -> list[str]:
    return sorted(p.name for p in (ctx.data_dir / "grids").iterdir())


def test_manifest_valid_and_complete_marker(env):
    ctx, _ = env
    result = build.build_grid(ctx, _builders())
    assert not result.reused
    assert result.grid.manifest["status"] == "complete"
    _assert_schema_valid(result.grid.manifest)
    assert (result.grid.path / "_COMPLETE").is_file()
    stored = json.loads((result.grid.path / "manifest.json").read_text())
    _assert_schema_valid(stored)
    layer = result.grid.layer("precip_annual")
    np.testing.assert_array_equal(
        layer[: SYNTH.shape[0], : SYNTH.shape[1]], SYNTH.layers["precip_annual"]
    )


def test_identical_rebuild_creates_no_new_directory(env):
    ctx, _ = env
    first = build.build_grid(ctx, _builders())
    dirs = _grid_dirs(ctx)
    calls = len(CALLS)
    second = build.build_grid(ctx, _builders())
    assert second.reused and second.grid.grid_id == first.grid.grid_id
    assert _grid_dirs(ctx) == dirs
    assert len(CALLS) == calls


def test_changed_layer_parameter_new_version_reuses_other_layers(env):
    ctx, cfg = env
    first = build.build_grid(ctx, _builders())
    data = json.loads((cfg / "layers.json").read_text())
    data["layers"][1]["params"] = {"block": 2}
    (cfg / "layers.json").write_text(json.dumps(data))
    CALLS.clear()
    second = build.build_grid(ctx, _builders())
    assert second.grid.grid_id != first.grid.grid_id
    assert len(_grid_dirs(ctx)) == 2
    assert CALLS == ["fx_terrain"]  # fx_climate files were copied, not rebuilt
    _assert_schema_valid(second.grid.manifest)
    old = (first.grid.path / "precip_annual.tif").read_bytes()
    assert (second.grid.path / "precip_annual.tif").read_bytes() == old


def test_failing_builder_gives_partial_manifest(env):
    ctx, _ = env
    result = build.build_grid(ctx, _builders(FailingTerrainBuilder))
    manifest = result.grid.manifest
    assert manifest["status"] == "partial"
    assert [m["layer_id"] for m in manifest["missing_layers"]] == ["slope_p90_1km"]
    assert [x["layer_id"] for x in manifest["layers"]] == ["precip_annual"]
    _assert_schema_valid(manifest)
    assert (result.grid.path / "_COMPLETE").is_file()
