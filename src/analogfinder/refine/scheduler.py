"""Bound-driven, cheap-first refinement schedule (research D-024, task T052).

Criterion groups come from each refinement criterion's Earth source: `terrain` when it is a DEM
source of `refine.terrain` (T050), `mineral` when it is the EMIT source of `refine.mineralogy`
(T051).

Upper bound of an area: for grid scores and already measured refinement scores `x_i` (known
ones only) plus optimistic estimates `u_j` for not-yet-measured criteria,
    S_ub(A) = exp( Σ_{i∈K∪A} w_i·ln x_i / Σ_{i∈K∪A} w_i )
maximised over availability scenarios A whose confidence C(A) = Σ_{K∪A} w ≥ min_confidence.
Scenarios are the subsets of the unmeasured groups (D-024, at most 4); within a group every
subset of its criteria is also tried, so a group that later turns out only partly known can
never push the final score above the bound (the bound only gets larger, never smaller).
A known score below its criterion's veto makes the area unrankable (bound 0).
Estimates: u = 1, except `traverse_slope` (the terrain criterion with quantity `slope_p90`)
when `refine.terrain_hint` is true: its score at the area's regional slope value ×
(1 − `refine.bound_margin`). Areas without EMIT coverage (cheap CMR search) drop the mineral
group from all scenarios.

Best-first loop over one queue keyed by the current bound (unrefined -> terrain-done ->
final score): take the top `refine.batch` entries; confirm fully refined entries whose final
score ≥ the best key among the other unconfirmed entries; run the terrain pass for unrefined
entries and the EMIT pass for terrain-done entries (or finalise them without EMIT coverage);
stop at `site_top_n` confirmed or when every rankable area is resolved (`bound_reached`: the
top list is proven complete, possibly shorter than `site_top_n`), or at
`refine.max_terrain_areas` / `refine.max_mineral_areas` (`cap_reached`). These are the values
of `run_record.refinement.stop` in results.schema.json.
Ties are broken by `area_id`, so the order is deterministic.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Callable, Mapping
from typing import Any

from ..scoring.aggregate import aggregate
from ..scoring.rules import score
from ..types import CandidateArea, Criterion, CriterionScore, GroupResult, Profile
from . import mineralogy, terrain

log = logging.getLogger("analogfinder.refine.scheduler")

TERRAIN, MINERAL = "terrain", "mineral"
LEVEL_NONE, LEVEL_TERRAIN, LEVEL_FULL = "none", "terrain", "full"


def criterion_groups(profile: Profile) -> dict[str, str]:
    """criterion_id -> group for refinement-scale criteria, from their Earth sources."""
    out = {}
    for c in profile.criteria:
        if c.comparison == "not_comparable" or c.evaluation_scale not in ("refinement", "both"):
            continue
        if any(s in terrain.DEM_SOURCES for s in c.earth_sources):
            out[c.id] = TERRAIN
        elif mineralogy.SOURCE_ID in c.earth_sources:
            out[c.id] = MINERAL
    return out


def _known(cs: CriterionScore | None) -> bool:
    return cs is not None and cs.state == "known" and cs.score is not None


def _gmean(items: list[tuple[float, float]]) -> float:
    """Weighted geometric mean of (weight, score) pairs; any zero score -> 0."""
    wsum = sum(w for w, _ in items)
    if any(x <= 0 for w, x in items if w > 0):
        return 0.0
    return math.exp(sum(w * math.log(x) for w, x in items if w > 0) / wsum)


def upper_bound(
    measured: Mapping[str, CriterionScore],
    estimates: Mapping[str, float],
    groups: Mapping[str, str],
    profile: Profile,
    impossible: frozenset[str] | set[str] = frozenset(),
) -> float | None:
    """Optimistic bound of the final score; None when no scenario reaches min_confidence.

    `measured`: scores of grid criteria and of refinement criteria already measured;
    `estimates`: u_j for refinement criteria not measured yet (their groups are open);
    `impossible`: groups that cannot have data (e.g. no EMIT coverage).
    """
    w = profile.weights
    crit = {c.id: c for c in profile.criteria}
    known = [
        (float(w.get(cid, 0.0)), cs.score)
        for cid, cs in measured.items()
        if cid in crit and crit[cid].comparison != "not_comparable" and _known(cs)
    ]
    for cid, cs in measured.items():
        veto = crit[cid].veto if cid in crit else None
        if _known(cs) and veto is not None and cs.score < veto:
            return 0.0
    open_ids = [cid for cid in estimates if groups.get(cid) not in impossible]
    best: float | None = None
    for n in range(len(open_ids) + 1):
        for subset in itertools.combinations(sorted(open_ids), n):
            items = known + [(float(w.get(cid, 0.0)), float(estimates[cid])) for cid in subset]
            conf = sum(x for x, _ in items)
            if conf + 1e-12 < profile.min_confidence or conf <= 0:
                continue
            s = _gmean(items)
            best = s if best is None else max(best, s)
    return best


def _value_for(c: Criterion, values: Mapping[str, Any]) -> Any:
    """Group values may be keyed by criterion id (contract) or by quantity (T051 today)."""
    if c.id in values:
        return values[c.id]
    return values.get(c.quantity, math.nan)


def _score_group(gr: GroupResult, ids: list[str], crit: dict[str, Criterion]) -> dict:
    out = {}
    for cid in ids:
        v = _value_for(crit[cid], gr.values)
        out[cid] = score(crit[cid], math.nan if v is None else v)
    return out


def _raw_group(gr: GroupResult, ids: list[str], crit: dict[str, Criterion]) -> dict:
    """criterion_id -> {value, source_id, coverage} for the results table (rank, T053)."""
    return {
        cid: {
            "value": _value_for(crit[cid], gr.values),
            "source_id": gr.source_id,
            "coverage": gr.coverage,
        }
        for cid in ids
    }


class _Entry:
    __slots__ = ("area", "level", "scores", "emit", "key", "final", "done")

    def __init__(self, area: CandidateArea):
        self.area = area
        self.level = LEVEL_NONE
        self.scores: dict[str, CriterionScore] = dict(area.grid_scores)
        self.emit: bool | None = None  # EMIT coverage, checked lazily
        self.key: float | None = None
        self.final = None
        self.done = False  # confirmed or unrankable


def _regional_slope_candidates(area: CandidateArea, profile: Profile, hints) -> list[float]:
    """Possible regional slope values of the area's representative cell.

    Exact when the caller passes `hints` (footprint value from screening). Otherwise rebuilt
    from the grid score's deviation: inside the range -> the range bounds; outside -> either
    side (the sign is not stored), and the caller takes the most optimistic candidate.
    """
    if hints and area.area_id in hints:
        return [float(hints[area.area_id])]
    for c in profile.criteria:
        if c.quantity == "slope_p90" and c.evaluation_scale == "grid":
            cs = area.grid_scores.get(c.id)
            if not _known(cs):
                return []
            lo, hi = (c.target or {}).get("min"), (c.target or {}).get("max")
            d = float(cs.deviation or 0.0)
            cands = [b for b in (lo, hi) if b is not None] if d == 0 else []
            if d > 0:
                cands = [float(hi) + d] if hi is not None else []
                cands += [float(lo) - d] if lo is not None else []
            return [float(x) for x in cands]
    return []


def schedule(
    areas: list[CandidateArea],
    ctx,
    terrain_fn: Callable[[CandidateArea, Any], GroupResult] = terrain.refine,
    mineral_fn: Callable[[CandidateArea, Any], GroupResult] = mineralogy.refine,
    coverage_fn: Callable[[Any, Any], bool] = mineralogy.emit_coverage,
    hints: Mapping[str, float] | None = None,
) -> tuple[list[CandidateArea], dict]:
    """Refine areas best-first; returns (areas with bounds/levels/refined scores, summary)."""
    profile: Profile = ctx.profile
    cfg = ctx.settings["refine"]
    top_n = int(ctx.settings["site_top_n"])
    batch = int(cfg["batch"])
    max_t, max_m = int(cfg["max_terrain_areas"]), int(cfg["max_mineral_areas"])
    margin, use_hint = float(cfg["bound_margin"]), bool(cfg["terrain_hint"])
    crit = {c.id: c for c in profile.criteria}
    groups = criterion_groups(profile)
    ids = {g: [cid for cid, gg in groups.items() if gg == g] for g in (TERRAIN, MINERAL)}
    slope_ids = [cid for cid in ids[TERRAIN] if crit[cid].quantity == "slope_p90"]

    def estimates(e: _Entry) -> dict[str, float]:
        est = {}
        open_groups = {LEVEL_NONE: (TERRAIN, MINERAL), LEVEL_TERRAIN: (MINERAL,)}.get(e.level, ())
        for g in open_groups:
            for cid in ids[g]:
                est[cid] = 1.0
        if use_hint and e.level == LEVEL_NONE:
            xs = _regional_slope_candidates(e.area, profile, hints)
            if xs:
                for cid in slope_ids:
                    best = max((score(crit[cid], x).score or 0.0) for x in xs)
                    est[cid] = best * (1.0 - margin)
        return est

    def rekey(e: _Entry) -> None:
        if e.level == LEVEL_FULL:
            e.final = aggregate(e.scores, profile)
            ok = (
                e.final.overall is not None and e.final.confidence + 1e-12 >= profile.min_confidence
            )
            e.key = e.final.overall if ok else None
            e.area.upper_bound = e.key if e.key is not None else 0.0
        else:
            impossible = {MINERAL} if e.emit is False else set()
            e.key = upper_bound(e.scores, estimates(e), groups, profile, impossible)
            e.area.upper_bound = e.key if e.key is not None else 0.0
        if e.key is None or e.key <= 0:
            e.done = True  # can never be ranked

    entries = {a.area_id: _Entry(a) for a in areas}
    for e in entries.values():
        rekey(e)
    confirmed: list[str] = []
    raw: dict[str, dict[str, dict]] = {}  # area_id -> criterion_id -> {value, source_id, coverage}
    n_terrain = n_mineral = n_emit = 0
    stop = "bound_reached"

    def order():
        live = [e for e in entries.values() if not e.done]
        return sorted(live, key=lambda e: (-(e.key or 0.0), e.area.area_id))

    while len(confirmed) < top_n:
        queue = order()
        if not queue:
            stop = "bound_reached"
            break
        progressed, capped = False, False
        for e in queue[:batch]:
            if len(confirmed) >= top_n:
                break
            if e.level == LEVEL_FULL:
                others = [o.key for o in order() if o is not e]
                if not others or e.key >= max(others):
                    e.done = True
                    confirmed.append(e.area.area_id)
                    progressed = True
                continue
            if e.level == LEVEL_NONE and ids[TERRAIN] and n_terrain >= max_t:
                capped = True
                continue
            if e.emit is None and ids[MINERAL]:  # cheap CMR search, only for areas we refine
                e.emit = bool(coverage_fn(e.area.footprint, ctx))
                n_emit += int(e.emit)
            if e.level == LEVEL_NONE:
                if ids[TERRAIN]:
                    gr = terrain_fn(e.area, ctx)
                    n_terrain += 1
                    raw.setdefault(e.area.area_id, {}).update(_raw_group(gr, ids[TERRAIN], crit))
                    new = _score_group(gr, ids[TERRAIN], crit)
                    e.scores.update(new)
                    e.area.refined.update(new)
                e.level = LEVEL_TERRAIN
            elif e.level == LEVEL_TERRAIN:
                if ids[MINERAL] and e.emit:
                    if n_mineral >= max_m:
                        capped = True
                        continue
                    gr = mineral_fn(e.area, ctx)
                    n_mineral += 1
                    raw.setdefault(e.area.area_id, {}).update(_raw_group(gr, ids[MINERAL], crit))
                    new = _score_group(gr, ids[MINERAL], crit)
                    e.scores.update(new)
                    e.area.refined.update(new)
                elif ids[MINERAL]:
                    for cid in ids[MINERAL]:  # no EMIT coverage: UNKNOWN, never "absent"
                        unk = CriterionScore(None, None, None, "unknown")
                        e.scores[cid] = unk
                        e.area.refined[cid] = unk
                e.level = LEVEL_FULL
            e.area.refinement_level = e.level
            rekey(e)
            progressed = True
        if len(confirmed) >= top_n:
            stop = "bound_reached"
            break
        if not progressed:
            stop = "cap_reached" if capped else "bound_reached"
            break

    for e in entries.values():
        e.area.refinement_level = e.level
        if e.level == LEVEL_NONE:
            e.area.status = "screened_only"
        if e.level == LEVEL_FULL and e.final is not None:
            e.area.aggregate = e.final
    summary = {
        "stop": stop,
        "proven_top": len(confirmed),
        "confirmed": confirmed,
        "terrain_areas": n_terrain,
        "mineral_areas": n_mineral,
        "emit_covered_areas": n_emit,
        "values": raw,  # raw refinement values per area (not part of run_record.refinement)
    }
    log.info(
        "refinement stop=%s proven_top=%d terrain=%d mineral=%d",
        stop,
        len(confirmed),
        n_terrain,
        n_mineral,
    )
    return list(areas), summary
