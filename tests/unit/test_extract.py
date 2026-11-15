"""T074: `analog extract` proposals for traverse_slope, roughness and mineral_classes."""

from __future__ import annotations

import hashlib
import json
import math
import re

import pytest

from analogfinder import cli
from analogfinder.planetary import crism, dem
from analogfinder.planetary import extract as ex
from tests.conftest import ROOT
from tests.fixtures.minerals_synthetic import write_crism_su
from tests.unit.test_planetary_dem import (
    LAT0,
    LON0,
    R_KM,
    SLOPE,
    FakeClient,
    eqc_plane,
    geo_plane,
    item,
)

PROFILE_PATH = ROOT / "profiles" / "mars-rover-jezero.json"
MC = json.loads((ROOT / "config" / "mineral_classes.json").read_text())


@pytest.fixture
def env(tmp_path, monkeypatch):
    mola, ctx = geo_plane(tmp_path / "mola.tif"), eqc_plane(tmp_path / "ctx.tif")
    sources = {
        "sources": [
            {"source_id": "mola-hrsc-blend", "endpoint": mola, "dataset_version": "v2"},
            {"source_id": "usgs-mars-dtm-stac", "collection": "c", "dataset_version": "1"},
            {"source_id": "crism-mtrdr-ode", "dataset_version": "verify"},
        ]
    }
    w, s, e, n = dem.footprint_bbox(LAT0, LON0, R_KM)
    client = FakeClient([item("CTX1", [w - 1, s - 1, e + 1, n + 1], href=ctx)])
    img = write_crism_su(tmp_path)  # D2300 block (fe_mg_smectite) + OLINDEX3 block (olivine)
    # move the synthetic scene (centred on 0°, 0°) onto the Jezero footprint
    k = math.pi / 180 * dem.MARS_RADIUS_M
    hdr = img.with_suffix(".hdr")
    ul_x, ul_y = LON0 * k - 25 * 100.0, LAT0 * k + 25 * 100.0
    hdr.write_text(
        re.sub(
            r"map info = \{[^}]*\}",
            f"map info = {{Mars Equirectangular, 1.0, 1.0, {ul_x}, {ul_y}, "
            f"100.0, 100.0, units=Meters}}",
            hdr.read_text(),
        )
    )
    monkeypatch.setattr(crism, "download", lambda obs, cache: [img])
    ode = lambda fp: [{"observation_id": "FRT0000ABCD", "files": []}]  # noqa: E731
    return sources, client, ode, tmp_path


def test_proposals_for_the_three_required_criteria(env):
    sources, client, ode, tmp = env
    profile = json.loads(PROFILE_PATH.read_text())
    rows = ex.propose(
        profile, sources, MC, data_dir=tmp / "data", today="2026-11-15", stac_client=client, ode=ode
    )
    by = {r["criterion"]: r for r in rows}
    assert {"traverse_slope", "roughness", "mineral_classes"} <= set(by)
    t = by["traverse_slope"]
    assert t["measured"]["value"] == pytest.approx(SLOPE, abs=0.1)
    assert (
        t["proposed"]["target"]["min"] == t["proposed"]["target"]["max"] == t["measured"]["value"]
    )
    src = t["proposed"]["sources.target"][0]
    assert src == {
        **src,
        "source_id": "usgs-mars-dtm-stac",
        "version": "1",
        "accessed": "2026-11-15",
    }
    assert "CTX1" in src["citation"]
    m = by["mineral_classes"]
    # synthetic CRISM: fe_mg_smectite 100/2250, olivine 25/2250 of valid pixels
    assert m["proposed"]["target"] == {"classes": ["fe_mg_smectite", "olivine"]}
    assert m["proposed"]["sources.target"][0]["source_id"] == "crism-mtrdr-ode"
    assert "FRT0000ABCD" in m["proposed"]["sources.target"][0]["citation"]
    assert by["aqueous_minerals"]["proposed"]["target"] == {"value": True}  # smectite is aqueous


def test_criteria_filter_and_min_fraction(env):
    sources, client, ode, tmp = env
    profile = json.loads(PROFILE_PATH.read_text())
    rows = ex.propose(
        profile,
        sources,
        MC,
        criteria=["mineral_classes"],
        data_dir=tmp / "d",
        min_class_fraction=0.02,
        stac_client=client,
        ode=ode,
    )
    assert [r["criterion"] for r in rows] == ["mineral_classes"]
    assert rows[0]["proposed"]["target"] == {"classes": ["fe_mg_smectite"]}  # olivine 0.011 < 0.02


def test_no_crism_data_is_reported(env):
    sources, client, _, tmp = env
    profile = json.loads(PROFILE_PATH.read_text())
    rows = ex.propose(
        profile,
        sources,
        MC,
        criteria=["mineral_classes"],
        data_dir=tmp / "d",
        stac_client=client,
        ode=lambda fp: [],
    )
    assert "no CRISM" in rows[0]["error"]


def test_cli_prints_and_never_edits_profile(env, monkeypatch, capsys):
    sources, client, ode, tmp = env
    real = ex.propose
    monkeypatch.setattr(
        cli.__dict__.get("config", __import__("analogfinder.config").config),
        "load_sources",
        lambda d=None: sources,
    )
    monkeypatch.setattr(
        ex, "propose", lambda *a, **k: real(*a, **{**k, "stac_client": client, "ode": ode})
    )
    before = hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest()
    code = cli.main(
        [
            "--data-dir",
            str(tmp / "data"),
            "extract",
            "--profile",
            str(PROFILE_PATH),
            "--criteria",
            "traverse_slope,roughness,mineral_classes",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    for cid in ("== traverse_slope", "== roughness", "== mineral_classes", "sources.target"):
        assert cid in out
    assert hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest() == before
