"""T083: deduplication against known analogs (spec US5 scenarios 1–3, SC-011)."""

from __future__ import annotations

import copy
import json
import logging

import numpy as np
import pytest

from analogfinder.config import validate_against
from analogfinder.dedup import dedup, haversine_km
from analogfinder.site import build
from analogfinder.types import CandidateArea, LandIndex, StageContext
from tests.conftest import ROOT
from tests.unit.test_scheduler import PROFILE, SETTINGS

FX = ROOT / "tests" / "fixtures"
SAMPLE = json.loads((FX / "results_sample.json").read_text())
INPUTS = json.loads((FX / "site_inputs_sample.json").read_text())
TOP = SAMPLE["candidates"][0]  # ranked, representative 23.275 N, 11.475 E


def ctx(tmp_path, config_dir=ROOT / "config"):
    return StageContext(
        "dedup",
        tmp_path,
        tmp_path,
        config_dir,
        SETTINGS,
        PROFILE,
        None,
        None,
        logging.getLogger("test"),
    )


def site(sid, lat, lon, radius_km=None, bodies=("Mars",), purposes=()):
    s = {
        "site_id": sid,
        "name": f"Site {sid}",
        "lat": lat,
        "lon": lon,
        "bodies": list(bodies),
        "purposes": list(purposes),
        "analog_for": "test",
        "reference": "test",
    }
    if radius_km is not None:
        s["radius_km"] = radius_km
    return s


def run(tmp_path, sites, results=SAMPLE, **kw):
    kw.setdefault("write", False)
    return dedup(results, ctx(tmp_path), known={"sites": sites}, **kw)


def labels(out):
    return {c["area_id"]: (c["label"], c["known_site"]) for c in out["candidates"]}


def test_within_radius_known_analog_with_site_name(tmp_path):
    rep = TOP["representative"]
    # no radius_km: settings.known_radius_default_km (50 km); the site is ~11 km away
    out = run(tmp_path, [site("a", rep["lat"] + 0.1, rep["lon"])])
    assert labels(out)[TOP["area_id"]] == ("known_analog", "Site a")


def test_outside_radius_new_candidate(tmp_path):
    rep = TOP["representative"]
    out = run(tmp_path, [site("a", rep["lat"] + 0.1, rep["lon"], radius_km=5)])
    assert labels(out)[TOP["area_id"]] == ("new_candidate", None)
    assert all(lab == "new_candidate" for lab, _ in labels(out).values())


def test_candidates_never_removed_and_input_untouched(tmp_path):
    before = copy.deepcopy(SAMPLE)
    rep = TOP["representative"]
    out = run(tmp_path, [site("a", rep["lat"], rep["lon"])])
    assert SAMPLE == before
    assert [c["area_id"] for c in out["candidates"]] == [c["area_id"] for c in SAMPLE["candidates"]]
    for a, b in zip(out["candidates"], SAMPLE["candidates"], strict=True):
        assert {k: v for k, v in a.items() if k not in ("label", "known_site")} == {
            k: v for k, v in b.items() if k not in ("label", "known_site")
        }
    assert out["run_record"]["dedup_applied"] is True


def test_nearest_site_wins_and_irrelevant_sites_ignored(tmp_path):
    rep = TOP["representative"]
    sites = [
        site("far", rep["lat"] + 0.3, rep["lon"]),  # ~33 km
        site("near", rep["lat"] + 0.1, rep["lon"]),  # ~11 km
        site("moon", rep["lat"], rep["lon"], bodies=("Moon",)),  # other body
        site("other", rep["lat"], rep["lon"], purposes=("crewed-base",)),  # other purpose
    ]
    out = run(tmp_path, sites)
    assert labels(out)[TOP["area_id"]] == ("known_analog", "Site near")
    assert out["run_record"]["dedup"]["sites_checked"] == ["far", "near"]


def test_distance_to_nearest_cell_not_representative(tmp_path):
    rep = TOP["representative"]
    # two cells: the representative and one 0.25° (~25 km) east; the site is 5 km east of that
    lat = np.array([rep["lat"], rep["lat"]])
    lon = np.array([rep["lon"], rep["lon"] + 0.25])
    land = LandIndex(np.zeros(2, np.int32), np.arange(2, dtype=np.int32), lat, lon, np.ones(2))
    area = CandidateArea(
        area_id=TOP["area_id"],
        cell_idx=np.array([0, 1]),
        n_cells=2,
        area_km2=50.0,
        bbox=(0, 0, 0, 0),
        centroid=(0, 0),
        representative=(rep["lat"], rep["lon"]),
        rep_idx=0,
        footprint=(rep["lat"], rep["lon"], 20.0),
        grid_scores={},
        refined={},
    )
    s = site("e", rep["lat"], rep["lon"] + 0.25 + 0.05 / np.cos(np.radians(rep["lat"])), 10)
    d_rep = float(haversine_km(s["lat"], s["lon"], rep["lat"], rep["lon"]))
    assert d_rep > 25
    assert labels(run(tmp_path, [s]))[TOP["area_id"]][0] == "new_candidate"  # representative
    out = run(tmp_path, [s], areas=[area], land=land)
    assert labels(out)[TOP["area_id"]] == ("known_analog", "Site e")


def test_real_known_analogs_config_labels_atacama(tmp_path):
    out = dedup(SAMPLE, ctx(tmp_path), write=False)  # config/known_analogs.json
    lab = labels(out)
    assert lab["mars-rover-jezero--24.10_-69.95"] == (
        "known_analog",
        "Atacama Desert - Yungay, Chile",
    )
    assert lab[TOP["area_id"]] == ("new_candidate", None)


def test_sc011_note_when_fewer_than_three_new(tmp_path):
    rep = TOP["representative"]
    out = run(tmp_path, [site("a", rep["lat"], rep["lon"], radius_km=5)])
    d = out["run_record"]["dedup"]
    assert (d["new_candidates"], d["known_analogs"]) == (2, 1)  # 3 ranked in the sample
    assert "1 of 3 ranked areas" in d["note"]
    none = run(tmp_path, [])["run_record"]["dedup"]
    assert none["new_candidates"] == 3 and none["note"] is None
    few = copy.deepcopy(SAMPLE)
    few["candidates"] = few["candidates"][:1]
    assert "only 1 area(s) ranked" in run(tmp_path, [], few)["run_record"]["dedup"]["note"]


def test_writes_results_dedup_json_only(tmp_path):
    out = run(tmp_path, [site("a", *TOP["representative"].values())], write=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["results.dedup.json"]
    on_disk = json.loads((tmp_path / "results.dedup.json").read_text())
    assert on_disk == out
    assert validate_against(on_disk, "results.schema.json", "results.dedup.json") == []


@pytest.mark.parametrize("deduped", [False, True])
def test_site_dedup_note_and_sections(tmp_path, deduped):
    results = SAMPLE
    if deduped:
        results = run(tmp_path, [site("a", *TOP["representative"].values(), radius_km=5)])
    out = tmp_path / "site"
    build.render(results, INPUTS, out, unvalidated=[])
    index = (out / "index.html").read_text()
    if not deduped:  # US5 scenario 3: no labels, note shown
        assert "Deduplication not applied" in index
        assert 'id="new"' not in index and "known_analog" not in index
    else:  # US5 scenario 2: new highlighted, known shown separately (not removed)
        assert "Deduplication not applied" not in index
        assert 'id="new"' in index and 'id="known"' in index
        assert 'class="new_candidate"' in index and 'class="known_analog"' in index
        assert "Site a" in index
