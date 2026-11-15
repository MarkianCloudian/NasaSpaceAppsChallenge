"""T051 on the synthetic EMIT granule (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from analogfinder.refine import mineralogy
from tests.conftest import ROOT
from tests.fixtures.fake_sources import fake_registry

SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())


def alias(reg):
    """The fixture registry serves the EMIT granule as `fx-emit`; expose it as the real id."""
    return SimpleNamespace(get=lambda _id: reg.get("fx-emit"))


def ctx(tmp_path, sources=None):
    return SimpleNamespace(
        settings=SETTINGS,
        config_dir=ROOT / "config",
        sources=sources or alias(fake_registry(tmp_path)),
    )


def area(lat=30.0, lon=10.0, r=1.0):
    return SimpleNamespace(area_id="a1", footprint=(lat, lon, r))


def test_classes_and_clusters(tmp_path):
    res = mineralogy.refine(area(), ctx(tmp_path))
    fr = res.values["mineral_class_fractions"]
    assert fr["sulfate"] > 0.5  # gypsum everywhere except the montmorillonite block
    assert fr["fe_mg_smectite"] > 0.05
    assert fr["carbonate"] == 0  # 2-pixel calcite cluster is below min_cluster_pixels
    assert fr["fe_oxide"] == 0  # hematite band depth 0.01 < min_band_depth
    assert res.values["aqueous_mineral_present"] is True
    assert res.coverage == pytest.approx(1.0)


def test_outside_emit_latitudes_is_unknown(tmp_path):
    res = mineralogy.refine(area(lat=60.0), ctx(tmp_path))
    assert res.values["mineral_class_fractions"] is None
    assert res.values["aqueous_mineral_present"] is None
    assert not mineralogy.emit_coverage((60.0, 10.0, 1.0), ctx(tmp_path))


def test_no_granule_is_unknown(tmp_path):
    reg = fake_registry(tmp_path)
    reg.get("fx-emit").search = lambda request: []
    c = ctx(tmp_path, alias(reg))
    assert not mineralogy.emit_coverage((30.0, 10.0, 1.0), c)
    res = mineralogy.refine(area(), c)
    assert res.values["aqueous_mineral_present"] is None


def test_partial_scene_coverage_is_unknown(tmp_path):
    # circle much larger than the 4.4 km scene -> valid pixels < min_coverage_fraction
    res = mineralogy.refine(area(r=20.0), ctx(tmp_path))
    assert res.coverage < 0.5
    assert res.values["mineral_class_fractions"] is None
