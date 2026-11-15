"""T053: synthetic run (grid → footprint → percentiles → areas → scheduler → rank)."""

from __future__ import annotations

import csv
import json
import logging

import numpy as np
import pytest

from analogfinder import errors
from analogfinder.config import validate_against
from analogfinder.footprint import focal_many
from analogfinder.rank import exit_code, rank
from analogfinder.refine import scheduler as sch
from analogfinder.scoring.percentile import Percentile
from analogfinder.scoring.rules import score
from analogfinder.types import CandidateArea, GroupResult, ScreeningResult, StageContext
from tests.conftest import ROOT
from tests.fixtures.synthetic import LAT_TOP, REGIONS, build_synthetic_grid
from tests.unit.test_scheduler import PROFILE, SETTINGS

LAYERS = json.loads((ROOT / "tests" / "fixtures" / "layers.json").read_text())
Q2L = {o["quantity"]: o["layer_id"] for e in LAYERS["layers"] for o in e["outputs"]}


def screening_and_areas():
    g = build_synthetic_grid()
    li = g.land_index()
    grid = [
        c
        for c in PROFILE.criteria
        if c.evaluation_scale == "grid" and c.comparison != "not_comparable"
    ]
    fp = focal_many(
        {c.id: (g.land_vector(Q2L[c.quantity]), c.footprint_statistic) for c in grid},
        li,
        PROFILE.radius_km,
        0.5,
        lat_top=LAT_TOP,
        grid_shape=g.shape,
        wrap_lon=False,
    )
    pct = {
        c.id: Percentile.build(fp[c.id], li.area_km2) for c in grid if c.comparison == "normalized"
    }
    scr = ScreeningResult(
        land=li,
        survivors=np.ones(li.rows.size, bool),
        screening_score=np.full(li.rows.size, np.nan),
        footprint=fp,
        percentiles=pct,
        population=("eligible", int(li.rows.size)),
        counts={
            "evaluated": int(li.rows.size),
            "rejected_by_constraint": 0,
            "rejected_by_criterion": {},
        },
    )
    areas = []
    for name in ("blob_a", "blob_b", "veto_area"):
        rs, cs = REGIONS[name]
        r, c = (rs.start + rs.stop) // 2, (cs.start + cs.stop) // 2
        idx = int(np.nonzero((li.rows == r) & (li.cols == c))[0][0])
        lat, lon = float(li.lat[idx]), float(li.lon[idx])
        areas.append(
            CandidateArea(
                area_id=name,
                cell_idx=np.array([idx]),
                n_cells=1,
                area_km2=float(li.area_km2[idx]),
                bbox=(lon, lat, lon, lat),
                centroid=(lat, lon),
                representative=(lat, lon),
                rep_idx=idx,
                footprint=(lat, lon, PROFILE.radius_km),
                grid_scores={x.id: score(x, float(fp[x.id][idx]), pct=pct.get(x.id)) for x in grid},
                refined={},
            )
        )
    return scr, areas


def ctx(tmp_path):
    return StageContext(
        "rank",
        tmp_path / "rank" / "0123456789abcdef",
        tmp_path,
        ROOT / "config",
        SETTINGS,
        PROFILE,
        None,
        None,
        logging.getLogger("test"),
    )


def terrain_fn(a, c):
    return GroupResult("terrain", {"traverse_slope": 6.0, "roughness": 2.0}, "nasadem-pc", 1.0)


def mineral_fn(a, c):
    return GroupResult(
        "mineral",
        {
            "mineral_class_fractions": {"fe_mg_smectite": 0.1, "carbonate": 0.04},
            "aqueous_mineral_present": True,
        },
        "emit-l2b-min",
        0.9,
    )


@pytest.fixture
def run(tmp_path):
    scr, areas = screening_and_areas()
    c = ctx(tmp_path)
    areas, summary = sch.schedule(areas, c, terrain_fn, mineral_fn, lambda fp, cc: True)
    sources = json.loads((ROOT / "config" / "sources.json").read_text())
    return rank(areas, scr, c, refinement=summary, sources_config=sources), c


def test_better_blob_ranked_first(run):
    res, _ = run
    by = {c["area_id"]: c for c in res["candidates"]}
    assert by["blob_b"]["rank"] == 1 and by["blob_a"]["rank"] == 2
    assert by["blob_b"]["overall_score"] >= by["blob_a"]["overall_score"]
    assert (
        by["veto_area"]["status"] == "rejected"
        and by["veto_area"]["rejected_by"] == "no_vegetation"
    )
    assert by["veto_area"]["rank"] is None and by["veto_area"]["overall_score"] is None
    assert exit_code(res) == errors.OK


def test_fr036_fields_and_schema(run):
    res, c = run
    assert validate_against(res, "results.schema.json", "results.json") == []
    top = res["candidates"][0]
    for k in (
        "overall_score",
        "confidence",
        "limiting_criterion",
        "analogy_limits",
        "label",
        "representative",
        "footprint",
        "upper_bound",
        "refinement_level",
    ):
        assert k in top
    rows = {r["criterion_id"]: r for r in top["results"]}
    for r in rows.values():
        for k in (
            "earth_value",
            "target",
            "deviation",
            "deviation_ratio",
            "score",
            "relative",
            "source_id",
            "state",
        ):
            assert k in r
    assert (
        rows["traverse_slope"]["scale_used"] == "refinement"
        and rows["traverse_slope"]["earth_value"] == 6.0
    )
    assert rows["traverse_slope"]["source_id"] == "nasadem-pc"
    assert rows["hyperarid"]["scale_used"] == "grid" and rows["hyperarid"]["relative"] is True
    assert rows["gravity"]["state"] == "not_comparable" and rows["gravity"]["score"] is None
    known_w = [r["weight_effective"] for r in top["results"] if r["state"] == "known"]
    assert sum(known_w) == pytest.approx(1.0)
    lim = " | ".join(top["analogy_limits"])
    assert "not reproducible on Earth: gravity" in lim
    assert "relative to eligible on Earth, not absolute: hyperarid" in lim
    assert "regional_slope: grid baseline is 926 m north-south" in lim


def test_files_written(run):
    res, c = run
    d = c.stage_dir
    assert json.loads((d / "results.json").read_text()) == res
    rr = json.loads((d / "run_record.json").read_text())
    assert rr["profile"]["id"] == "mars-rover-jezero" and rr["dedup_applied"] is False
    has_placeholder = any(c.value_status == "placeholder" for c in PROFILE.criteria)
    assert rr["placeholder_values"] is has_placeholder  # all Jezero targets sourced (T036)
    assert rr["refinement"]["stop"] == "bound_reached"
    assert rr["percentile_population"]["name"] == "eligible"
    assert {s["source_id"] for s in rr["sources"]} >= {"nasadem-pc", "emit-l2b-min"}
    rows = list(csv.DictReader(open(d / "results.csv", encoding="utf-8")))
    assert len(rows) == len(res["candidates"]) * len(PROFILE.criteria)


def test_unknown_from_failed_source_and_no_candidates(tmp_path):
    scr, areas = screening_and_areas()
    c = ctx(tmp_path)

    def failed(a, cc):
        nan = float("nan")
        return GroupResult("terrain", {"traverse_slope": nan, "roughness": nan}, None, None)

    areas, summary = sch.schedule(areas, c, failed, mineral_fn, lambda fp, cc: True)
    res = rank(areas, scr, c, refinement=summary)
    refined = next(c for c in res["candidates"] if c["refinement_level"] != "none")
    r = next(x for x in refined["results"] if x["criterion_id"] == "traverse_slope")
    assert r["state"] == "unknown" and r["note"] == "source failed"
    assert exit_code(res) in (errors.PARTIAL_RESULT, errors.NO_CANDIDATES)
    assert any("no Earth data: traverse_slope" in x for x in refined["analogy_limits"])
