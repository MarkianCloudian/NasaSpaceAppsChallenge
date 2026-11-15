"""T040: both MODIS CMG registry entries (LST and NDVI) run through the same builder."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from analogfinder.errors import ConfigError
from analogfinder.grid import cells
from analogfinder.grid.builders import modis_cmg as m

ROOT = Path(__file__).resolve().parents[2]
LAYERS = {e["layer_id"]: e for e in json.loads((ROOT / "config/layers.json").read_text())["layers"]}


def test_both_entries_use_modis_cmg():
    assert LAYERS["mod11c3_lst"]["builder"] == "modis_cmg"
    assert LAYERS["mod13c2_ndvi"]["builder"] == "modis_cmg"
    ndvi = LAYERS["mod13c2_ndvi"]["params"]
    assert ndvi["variables"] == {"ndvi": "CMG 0.05 Deg Monthly NDVI"}
    assert ndvi["scale"] == 0.0001
    assert ndvi["temporal_reduce"] == "max"
    assert ndvi["qc"]["keep"] in m.QC_RULES
    assert [o["layer_id"] for o in LAYERS["mod13c2_ndvi"]["outputs"]] == ["ndvi_max"]


def test_no_product_specific_code():
    import ast

    tree = ast.parse((ROOT / "src/analogfinder/grid/builders/modis_cmg.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "ndvi" not in node.value.lower() or len(node.value) > 80  # docstrings only
        if isinstance(node, ast.Name | ast.Attribute | ast.arg | ast.FunctionDef):
            ident = getattr(node, "id", None) or getattr(node, "attr", None)
            ident = ident or getattr(node, "arg", None) or getattr(node, "name", "")
            assert "ndvi" not in ident.lower()


def test_temporal_reduce_recipe():
    fn, roles = m.temporal_reduce_recipe(LAYERS["mod13c2_ndvi"]["params"])
    assert roles == ("ndvi",)
    stack = np.full((12, 1, 3), np.nan, dtype="float32")
    stack[3, 0] = [0.05, 0.9, np.nan]
    stack[8, 0] = [0.02, 0.4, np.nan]
    out = fn({"ndvi": stack})
    assert out[0, 0] == pytest.approx(0.05) and out[0, 1] == pytest.approx(0.9)
    assert np.isnan(out[0, 2])
    with pytest.raises(ConfigError):
        m.temporal_reduce_recipe({"variables": {"a": "x"}})
    with pytest.raises(ConfigError):
        m.temporal_reduce_recipe({"variables": {"a": "x", "b": "y"}, "temporal_reduce": "max"})


@pytest.mark.parametrize("layer_id", ["mod11c3_lst", "mod13c2_ndvi"])
def test_builder_runs_each_entry(layer_id, tmp_path, monkeypatch):
    entry = LAYERS[layer_id]
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for doy in ("001", "182"):
        (src_dir / f"PROD.A2019{doy}.061.x.hdf").write_bytes(b"")
    shape = (cells.N_ROWS, cells.N_COLS)
    values = {"day": 40.0, "night": 10.0, "ndvi": 0.0}

    def fake_read(path, variables, scale, offset, qc):
        high = "A2019182" in path.name
        out = {}
        for role in variables:
            v = values[role] + (0.5 if role == "ndvi" and high else 0.0)
            out[role] = np.full(shape, v, dtype="float32")
        return out

    monkeypatch.setattr(m, "read_month", fake_read)
    source = SimpleNamespace(
        entry={"dataset": "PROD", "dataset_version": "061"},
        fetch=lambda req: SimpleNamespace(path=src_dir),
    )
    ctx = SimpleNamespace(
        sources={entry["source_id"]: source},
        settings={"grid": {"reference_years": [2019]}},
        stage_dir=tmp_path / "stage",
    )
    ctx.sources = SimpleNamespace(get=lambda sid: source)
    layers = m.ModisCmgBuilder().build(entry, ctx)
    assert [layer["layer_id"] for layer in layers] == [o["layer_id"] for o in entry["outputs"]]
    for layer in layers:
        assert (ctx.stage_dir / layer["file"]).is_file()
        assert layer["qc_rule"].startswith(entry["params"]["qc"]["keep"])
    if layer_id == "mod13c2_ndvi":
        arr = cells.read_layer(ctx.stage_dir / "ndvi_max.tif")
        assert float(np.nanmax(arr)) == pytest.approx(0.5)
