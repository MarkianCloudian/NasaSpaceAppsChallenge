"""Grid build runs a layer's registry `fallback` when the primary builder fails (D-008, D-019);
every real builder name resolves to its class."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from analogfinder import config
from analogfinder.grid import build, cells
from analogfinder.types import StageContext

ROOT = Path(__file__).resolve().parents[2]
CALLS: list[tuple[str, str]] = []


class Writer:
    fail = False

    def build(self, entry, ctx):
        CALLS.append((entry["builder"], entry["source_id"]))
        if self.fail:
            raise RuntimeError(f"{entry['source_id']} down")
        out = []
        for o in entry["outputs"]:
            name = f"{o['layer_id']}.tif"
            cells.write_layer(
                Path(ctx.stage_dir) / name, np.full((cells.N_ROWS, cells.N_COLS), 2.0, "float32")
            )
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


class Failing(Writer):
    fail = True


@pytest.fixture
def ctx(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "tests" / "fixtures" / "config", cfg)
    layers = json.loads((cfg / "layers.json").read_text())
    for e in layers["layers"]:
        if e["layer_id"] == "fx_climate":
            e["fallback"] = {"builder": "gridded_netcdf", "source_id": "fx-dem", "params": {}}
    (cfg / "layers.json").write_text(json.dumps(layers))
    CALLS.clear()
    return StageContext(
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


def test_fallback_used_when_primary_fails(ctx):
    builders = {"climatology_rest": Failing, "dem_block_stats": Writer, "gridded_netcdf": Writer}
    res = build.build_grid(ctx, builders)
    m = res.grid.manifest
    assert m["status"] == "complete" and "missing_layers" not in m
    precip = next(x for x in m["layers"] if x["layer_id"] == "precip_annual")
    assert precip["source_id"] == "fx-dem"  # manifest names the source that served it
    assert ("climatology_rest", "fx-climate") in CALLS and ("gridded_netcdf", "fx-dem") in CALLS


def test_primary_and_fallback_fail_gives_partial(ctx):
    builders = {"climatology_rest": Failing, "dem_block_stats": Writer, "gridded_netcdf": Failing}
    m = build.build_grid(ctx, builders).grid.manifest
    assert m["status"] == "partial"
    (miss,) = m["missing_layers"]
    assert miss["layer_id"] == "precip_annual"
    assert "primary failed" in miss["reason"] and "fallback failed" in miss["reason"]


def test_fallback_entry_keeps_primary_outputs():
    entry = {
        "layer_id": "x",
        "builder": "a",
        "source_id": "s1",
        "params": {"p": 1},
        "resampling": "bilinear",
        "outputs": [{"layer_id": "o"}],
        "fallback": {"builder": "b", "source_id": "s2", "params": {"q": 2}},
    }
    fb = build.fallback_entry(entry)
    assert fb["builder"] == "b" and fb["source_id"] == "s2" and fb["params"] == {"q": 2}
    assert fb["outputs"] == entry["outputs"] and fb["layer_id"] == "x" and "fallback" not in fb
    assert build.fallback_entry({**entry, "fallback": None}) is None


def test_fallback_version_enters_fingerprint():
    entry = {"layer_id": "x", "source_id": "s1", "fallback": {"source_id": "s2"}}
    a = build.layer_fingerprint(entry, {"s1": "1", "s2": "1"})
    b = build.layer_fingerprint(entry, {"s1": "1", "s2": "2"})
    assert a != b


@pytest.mark.parametrize("name", sorted(build.BUILDERS))
def test_every_registered_builder_resolves(name):
    assert callable(build.resolve_builder(name).build)
