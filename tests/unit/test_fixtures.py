"""T034: the synthetic grid, fixture registry, frozen sample profile and fake sources."""

from __future__ import annotations

import json
import math

import h5py
import numpy as np
import pytest

from analogfinder.config import validate_against
from analogfinder.profiles.load import content_hash
from analogfinder.types import Profile
from tests.conftest import ROOT
from tests.fixtures.fake_sources import DEM_SLOPE_DEG, fake_registry
from tests.fixtures.synthetic import REGIONS, build_synthetic_grid

FIX = ROOT / "tests" / "fixtures"
LAYERS = json.loads((FIX / "layers.json").read_text())
SAMPLE = json.loads((FIX / "profiles" / "sample-frozen@1.0.0.json").read_text())
OUTPUTS = {o["layer_id"]: o for e in LAYERS["layers"] for o in e["outputs"]}


def test_registry_and_sources_are_schema_valid():
    assert validate_against(LAYERS, "layers.schema.json", "layers.json") == []
    srcs = json.loads((FIX / "sources.json").read_text())
    assert validate_against(srcs, "sources.schema.json", "sources.json") == []
    ids = {s["source_id"] for s in srcs["sources"]}
    assert {e["source_id"] for e in LAYERS["layers"]} <= ids


def test_grid_has_every_registry_output():
    g = build_synthetic_grid()
    assert set(OUTPUTS) == set(g.layers)
    assert all(a.shape == (20, 40) and a.dtype == np.float32 for a in g.layers.values())


def test_regions():
    g = build_synthetic_grid()
    L = g.layers
    a, b = REGIONS["blob_a"], REGIONS["blob_b"]
    assert np.all(L["lc_frac_barren"][a] > 0.9) and np.all(L["ndvi_max"][b] < 0.1)
    assert L["precip_annual"][b].max() < L["precip_annual"][a].min()  # blob_b driest
    assert np.all(L["ndvi_max"][REGIONS["veto_area"]] >= 0.5)
    assert np.isnan(L["precip_annual"][REGIONS["missing_core"]]).all()
    assert np.all(L["ndvi_max"][REGIONS["missing_area"]] < 0.1)  # Mars-like margin
    assert not g.land_mask[REGIONS["sea"]].any()
    li = g.land_index()
    assert li.rows.size == 20 * 38 and np.isfinite(g.land_vector("lst_amp")).all()


def test_sample_frozen_profile():
    assert validate_against(SAMPLE, "profile.schema.json", "sample") == []
    assert SAMPLE["content_hash"] == content_hash(SAMPLE)
    assert sum(SAMPLE["weights"].values()) == pytest.approx(1.0, abs=1e-9)
    p = Profile.from_frozen_json(SAMPLE)
    assert p.ref == "sample-frozen@1.0.0"
    for c in p.criteria:
        if c.evaluation_scale == "grid" and c.comparison != "not_comparable":
            assert any(c.quantity in (o["quantity"], k) for k, o in OUTPUTS.items()), c.id


def test_fake_sources(tmp_path):
    reg = fake_registry(tmp_path)
    bbox = [77.2, 18.25, 77.7, 18.6]
    dem = reg.get("fx-fine-dem")
    r1, r2 = dem.fetch({"bounding_box": bbox}), dem.fetch({"bounding_box": bbox})
    assert r1.path == r2.path and r1.source_id == "fx-fine-dem"
    import rasterio

    with rasterio.open(next(r1.path.glob("*.tif"))) as ds:
        z = ds.read(1)
        dx = ds.res[0] * math.pi * 6371000 / 180 * math.cos(math.radians(18.425))
    slope = math.degrees(math.atan((z[0, 1] - z[0, 0]) / dx))
    assert slope == pytest.approx(DEM_SLOPE_DEG, abs=0.01)
    emit = reg.get("fx-emit").fetch({"bounding_box": bbox})
    with h5py.File(next(emit.path.glob("EMIT_*.nc"))) as h:
        gt = h.attrs["geotransform"]
    assert gt[0] < 77.45 < gt[0] + 40 * gt[1] and gt[3] + 40 * gt[5] < 18.425 < gt[3]
