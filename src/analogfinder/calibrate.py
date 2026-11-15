"""Calibration against known Earth analog sites (plan G2, research D-018, D-022, D-025, T077).

`calibrate(results, screening, ctx) -> dict` (the `calibration.json` content, data-model
*Calibration Report*):

  1. relevant sites: `config/known_analogs.json` entries whose `bodies` contain the profile body
     and whose `purposes` is empty or contains the profile purpose;
  2. each relevant site is evaluated on a circle of the profile radius **centred on the site's
     own coordinates** (D-022): the grid-scale footprint values are taken at the land cell that
     contains the site (from the screening stage; when that cell is not land, e.g. a lake, the
     nearest land cell within the radius is used and recorded in `cell`);
  3. hard search constraints at that cell (latitude range, land-cover fraction limits on the
     footprint mean, as in screening) → `in_scope: false` with `out_of_scope_reason`; such a
     site is not refined or scored;
  4. vetoes: a vetoed site keeps `rejected_by` and its score is still computed (vetoes ignored
     for the score only);
  5. refinement for that circle with the same group functions as the scheduler (terrain, then
     EMIT where there is coverage, else the mineral criteria are UNKNOWN), full score
     (scoring.aggregate);
  6. conservative rank (D-025): `rank = 1 + #{areas : final score > S_site, or (not fully
     refined and upper_bound > S_site)}`, `percentile_rank = rank / #areas that passed
     screening` (= candidates in results.json); `area_id` of the candidate area containing the
     site cell, if any;
  7. `flag_for_review` with `flag_reasons` (D-018, SC-006): `no_known_analog_in_scope` when no
     relevant site is in scope, `no_known_analog_in_top_20pct` when no in-scope, not vetoed site
     with enough confidence has `percentile_rank ≤ 0.2`, tested as `rank ≤ max(1, ⌊0.2·n⌋)`
     (identical for n ≥ 5 areas; with fewer areas rank 1 still counts, see `in_top`).

  8. `stability`: weight stability of the ranked areas (`weight_stability`, T078).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from . import config, stage_io
from .footprint import focal_many
from .refine import mineralogy, terrain
from .refine.scheduler import MINERAL, TERRAIN, _score_group, criterion_groups
from .scoring.aggregate import aggregate
from .scoring.rules import score
from .screening import _geometry, grid_criteria
from .types import (
    CandidateArea,
    CriterionScore,
    GroupResult,
    Profile,
    ScreeningResult,
    StageContext,
)

log = logging.getLogger("analogfinder.calibrate")

TOP_FRACTION = 0.2  # SC-006
EARTH_R_KM = 6371.0
KM_PER_DEG = 111.195


def relevant_sites(known: Mapping[str, Any], profile: Profile) -> list[dict]:
    return [
        s
        for s in known.get("sites", [])
        if profile.body in s["bodies"]
        and (not s.get("purposes") or profile.purpose in s["purposes"])
    ]


def _site_cell(lat: float, lon: float, land, geo: dict, radius_km: float) -> int | None:
    """Land index of the cell containing (lat, lon), else the nearest land cell within radius."""
    cell = geo["cell_deg"]
    h, w = geo["grid_shape"]
    lon_left = geo["lon_left"]
    r = math.floor((geo["lat_top"] - lat) / cell)
    c = math.floor((lon - lon_left) / cell)
    if geo["wrap_lon"]:
        c %= w
    hit = np.flatnonzero((land.rows == r) & (land.cols == c)) if 0 <= r < h else []
    if len(hit):
        return int(hit[0])
    dlat = radius_km / KM_PER_DEG
    near = np.flatnonzero(np.abs(land.lat - lat) <= dlat)
    if not near.size:
        return None
    p1, p2 = np.radians(lat), np.radians(land.lat[near])
    dl = np.radians(land.lon[near] - lon)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    d = 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    k = int(np.argmin(d))
    return int(near[k]) if d[k] <= radius_km else None


def _constraint_values(ctx: StageContext, land, idx: list[int], geo: dict) -> dict:
    """Footprint mean of the land-cover fractions the constraints need, at the given cells."""
    profile = ctx.profile
    sc = profile.search_constraints or {}
    classes = sorted(
        set(sc.get("max_landcover_fraction") or {})
        | ({"barren"} if "min_barren_fraction" in sc else set())
    )
    if not classes or not idx:
        return {}
    targets = np.zeros(land.rows.size, bool)
    targets[idx] = True
    jobs = {k: (ctx.grid.land_vector(f"lc_frac_{k}"), "mean") for k in classes}
    return focal_many(
        jobs,
        land,
        profile.radius_km,
        float(ctx.settings["footprint"]["min_valid_fraction"]),
        cell_deg=geo["cell_deg"],
        lat_top=geo["lat_top"],
        grid_shape=geo["grid_shape"],
        wrap_lon=geo["wrap_lon"],
        targets=targets,
    )


def _out_of_scope(profile: Profile, lat: float, i: int, lc: Mapping[str, np.ndarray]) -> str | None:
    sc = profile.search_constraints or {}
    rng = sc.get("lat_range")
    if rng and not (min(rng) <= lat <= max(rng)):
        return f"latitude {lat:.2f} outside the search range [{min(rng)}, {max(rng)}]"
    for k, mx in sorted((sc.get("max_landcover_fraction") or {}).items()):
        v = float(lc[k][i])
        if not math.isfinite(v):
            return f"land-cover fraction {k} unknown (no data), constraint cannot be verified"
        if v > mx:
            return f"land-cover fraction {k} {v:.2f} > {mx}"
    if "min_barren_fraction" in sc:
        v = float(lc["barren"][i])
        if not math.isfinite(v):
            return "barren fraction unknown (no data), constraint cannot be verified"
        if v < sc["min_barren_fraction"]:
            return f"barren fraction {v:.2f} < {sc['min_barren_fraction']}"
    return None


def _containing_area(i: int, results: dict, areas, lat: float, lon: float) -> str | None:
    if areas is not None:
        for a in areas:
            if i in set(np.asarray(a.cell_idx).tolist()):
                return a.area_id
        return None
    # without the stage's areas: smallest candidate bbox containing the site cell
    inside = [
        c
        for c in results.get("candidates", [])
        if c["bbox"][0] <= lon <= c["bbox"][2] and c["bbox"][1] <= lat <= c["bbox"][3]
    ]
    if not inside:
        return None
    return min(inside, key=lambda c: (c["n_cells"], c["area_id"]))["area_id"]


def in_top(rank: int, n_passed: int) -> bool:
    """`percentile_rank ≤ 0.2` as `rank ≤ max(1, ⌊0.2·n⌋)` (D-025): identical for n ≥ 5; with
    fewer areas only rank 1 qualifies (rank 1 = no area is, or could be, better)."""
    return n_passed > 0 and rank <= max(1, math.floor(TOP_FRACTION * n_passed + 1e-9))


def conservative_rank(site_score: float, candidates: list[dict]) -> int:
    """1 + areas whose final score, or (not fully refined) upper bound, exceeds the site (D-025)."""
    ahead = 0
    for c in candidates:
        if c["status"] == "ranked" and c.get("overall_score") is not None:
            ahead += c["overall_score"] > site_score
        elif c.get("refinement_level") != "full":
            ahead += (c.get("upper_bound") or 0.0) > site_score
    return 1 + int(ahead)


def calibrate(
    results: dict,
    screening: ScreeningResult,
    ctx: StageContext,
    *,
    areas: list[CandidateArea] | None = None,
    known: Mapping[str, Any] | None = None,
    terrain_fn: Callable[[CandidateArea, Any], GroupResult] = terrain.refine,
    mineral_fn: Callable[[CandidateArea, Any], GroupResult] = mineralogy.refine,
    coverage_fn: Callable[[Any, Any], bool] = mineralogy.emit_coverage,
    write: bool = True,
) -> dict:
    profile: Profile = ctx.profile
    if known is None:
        known = config.load_known_analogs(ctx.config_dir)
    sites = relevant_sites(known, profile)
    land = screening.land
    geo = _geometry(ctx.grid)
    cell = (getattr(ctx.grid, "manifest", None) or {}).get("cell") or {}
    geo["lon_left"] = float(cell.get("origin", [-180.0])[0])
    radius = profile.radius_km
    crit = {c.id: c for c in profile.criteria}
    gcrit = grid_criteria(profile)
    groups = criterion_groups(profile)
    ids = {g: sorted(cid for cid, gg in groups.items() if gg == g) for g in (TERRAIN, MINERAL)}
    no_veto = replace(profile, criteria=tuple(replace(c, veto=None) for c in profile.criteria))
    candidates = results.get("candidates", [])
    n_passed = len(candidates)

    cells = {s["site_id"]: _site_cell(s["lat"], s["lon"], land, geo, radius) for s in sites}
    lc = _constraint_values(ctx, land, sorted({i for i in cells.values() if i is not None}), geo)

    out = []
    for s in sites:
        sid, lat, lon = s["site_id"], float(s["lat"]), float(s["lon"])
        rec: dict[str, Any] = {
            "site_id": sid,
            "name": s["name"],
            "in_scope": False,
            "out_of_scope_reason": None,
            "footprint": {"lat": lat, "lon": lon, "radius_km": radius},
            "cell": None,
            "rejected_by": None,
            "area_id": None,
            "rank": None,
            "percentile_rank": None,
            "overall_score": None,
            "confidence": None,
            "limiting_criterion": None,
        }
        out.append(rec)
        i = cells[sid]
        if i is None:
            rec["out_of_scope_reason"] = "no land cell of the grid within the profile radius"
            continue
        rec["cell"] = {"lat": float(land.lat[i]), "lon": float(land.lon[i])}
        reason = _out_of_scope(profile, float(land.lat[i]), i, lc)
        if reason:
            rec["out_of_scope_reason"] = reason
            continue
        rec["in_scope"] = True
        rec["area_id"] = _containing_area(i, results, areas, float(land.lat[i]), float(land.lon[i]))

        scores: dict[str, CriterionScore] = {
            c.id: score(c, float(screening.footprint[c.id][i]), pct=screening.percentiles.get(c.id))
            for c in gcrit
        }
        circle = CandidateArea(
            area_id=f"known-{sid}",
            cell_idx=np.array([i], dtype=np.int64),
            n_cells=1,
            area_km2=float(land.area_km2[i]),
            bbox=(lon, lat, lon, lat),
            centroid=(lat, lon),
            representative=(lat, lon),
            rep_idx=i,
            footprint=(lat, lon, radius),
            grid_scores=dict(scores),
            refined={},
        )
        if ids[TERRAIN]:
            scores.update(_score_group(terrain_fn(circle, ctx), ids[TERRAIN], crit))
        if ids[MINERAL]:
            if coverage_fn(circle.footprint, ctx):
                scores.update(_score_group(mineral_fn(circle, ctx), ids[MINERAL], crit))
            else:  # no EMIT coverage: UNKNOWN, never "absent"
                scores.update(
                    {cid: CriterionScore(None, None, None, "unknown") for cid in ids[MINERAL]}
                )

        rec["rejected_by"] = aggregate(scores, profile).rejected_by
        agg = aggregate(scores, no_veto)
        rec["overall_score"] = agg.overall
        rec["confidence"] = agg.confidence
        rec["limiting_criterion"] = agg.limiting
        if agg.overall is not None:
            rec["rank"] = conservative_rank(agg.overall, candidates)
            rec["percentile_rank"] = rec["rank"] / n_passed if n_passed else None

    in_scope = [r for r in out if r["in_scope"]]
    top = [
        r
        for r in in_scope
        if r["rejected_by"] is None
        and r["percentile_rank"] is not None
        and r["confidence"] + 1e-12 >= profile.min_confidence
        and in_top(r["rank"], n_passed)
    ]
    reasons = []
    if not in_scope:
        reasons.append("no_known_analog_in_scope")
    if not top:
        reasons.append("no_known_analog_in_top_20pct")
    report = {
        "profile": {"id": profile.profile_id, "version": profile.version},
        "run_id": (results.get("run_record") or {}).get("run_id"),
        "areas_passed_screening": n_passed,
        "known_sites": out,
        "flag_for_review": bool(reasons),
        "flag_reasons": reasons,
        "stability": weight_stability(results, profile, ctx.settings["stability"]),
    }
    log.info(
        "calibration: %d relevant sites, %d in scope, %d in top 20%%, flag=%s",
        len(sites),
        len(in_scope),
        len(top),
        bool(reasons),
    )
    if write:
        d = Path(ctx.stage_dir)
        d.mkdir(parents=True, exist_ok=True)
        stage_io.write_json(d / "calibration.json", report)
    return report


def weight_stability(results: dict, profile: Profile, cfg: Mapping[str, Any]) -> dict:
    """Weight stability (plan G3, research D-014, T078).

    `cfg` = settings `stability` {draws, range, seed, top_k}. Each draw multiplies every category
    weight by U(1 − range, 1 + range) (numpy default_rng(seed)), keeps the within-category split
    and re-aggregates the stored per-criterion scores of the ranked areas (weighted geometric
    mean over KNOWN scores, as scoring.aggregate; no new data access). Ranked areas passed their
    vetoes, which do not depend on weights. Reported: for each of the baseline top `top_k`
    areas the share of draws in which it stays in the top `top_k`.
    """
    draws, r, seed, k = int(cfg["draws"]), float(cfg["range"]), int(cfg["seed"]), int(cfg["top_k"])
    ranked = sorted(
        (c for c in results.get("candidates", []) if c["status"] == "ranked"),
        key=lambda c: c["rank"],
    )
    crit = [
        c
        for c in profile.criteria
        if c.comparison != "not_comparable" and profile.weights.get(c.id)
    ]
    cats = sorted({c.category for c in crit})
    out = {"draws": draws, "range": r, "seed": seed, "top_k": k, "candidates": []}
    if not ranked or not crit:
        return out
    s = np.full((len(ranked), len(crit)), np.nan)
    pos = {c.id: j for j, c in enumerate(crit)}
    for i, cand in enumerate(ranked):
        for res in cand["results"]:
            j = pos.get(res["criterion_id"])
            if j is not None and res["state"] == "known" and res["score"] is not None:
                s[i, j] = float(res["score"])
    known = np.isfinite(s)
    pos_ok = known & (np.nan_to_num(s, nan=1.0) > 0)
    zero = (known & ~pos_ok).any(axis=1)  # a known score of 0 gives 0 (scoring.aggregate)
    logs = np.log(np.where(pos_ok, s, 1.0))
    w0 = np.array([float(profile.weights[c.id]) for c in crit])
    cat_of = np.array([cats.index(c.category) for c in crit])
    rng = np.random.default_rng(seed)
    f = rng.uniform(1.0 - r, 1.0 + r, size=(draws, len(cats)))
    w = w0[None, :] * f[:, cat_of]
    w /= w.sum(axis=1, keepdims=True)
    num = w @ logs.T  # (draws, areas)
    den = w @ known.T.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        overall = np.where(den > 0, np.exp(num / den), np.nan)
    overall = np.where(zero[None, :], 0.0, overall)
    # ties keep the baseline order (stable sort over areas listed in baseline rank order)
    order = np.argsort(-np.nan_to_num(overall, nan=-1.0), axis=1, kind="stable")
    position = np.empty_like(order)
    np.put_along_axis(position, order, np.arange(len(ranked))[None, :], axis=1)
    share = (position < k).mean(axis=0)
    out["candidates"] = [
        {"area_id": ranked[i]["area_id"], "share_in_top_k": float(share[i])}
        for i in range(min(k, len(ranked)))
    ]
    return out
