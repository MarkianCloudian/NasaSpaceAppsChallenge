"""Candidate areas from screening survivors, for presentation only (plan E2, research D-013,
D-017, D-024, task T049).

`group(screening, ctx) -> list[CandidateArea]`:
  1. cells that survived screening with screening score ≥ `screen_min_score` form 8-connected
     components (scipy.ndimage.label; on the global grid components wrap across ±180°);
  2. a component larger than `max_area_km2` is split on a fixed tile grid of side
     sqrt(max_area_km2) km aligned to the cells, so separate maxima become separate candidates;
  3. per area: `n_cells`, `area_km2`, `bbox` (cell edges), area-weighted `centroid`,
     `representative` = the cell with the highest screening score (ties: northernmost, then
     westernmost), `footprint` = (representative lat, lon, profile radius); layer values are
     never averaged over the area: `grid_scores` are the footprint values at the representative
     cell, scored (T028);
  4. `area_id` = "<profile_id>-<lat:.2f>_<lon:.2f>" of the representative cell (stable);
  5. `upper_bound` with all refinement groups estimated (T052 `initial_bounds`, exact regional
     slope hint from the footprint value at the representative cell). No fixed top K.
"""

from __future__ import annotations

import logging
import math

import numpy as np
from scipy import ndimage

from .refine.scheduler import initial_bounds
from .scoring.rules import score
from .screening import _geometry, grid_criteria
from .types import CandidateArea, ScreeningResult, StageContext

log = logging.getLogger("analogfinder.grouping")
KM_PER_DEG = 111.195


def _labels(mask: np.ndarray, wrap: bool) -> tuple[np.ndarray, int]:
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
    if wrap and n:
        parent = list(range(n + 1))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        h = mask.shape[0]
        for r in range(h):  # east edge touches west edge (8-connectivity across the seam)
            a = lab[r, -1]
            if not a:
                continue
            for rr in (r - 1, r, r + 1):
                if 0 <= rr < h and lab[rr, 0]:
                    pa, pb = find(a), find(lab[rr, 0])
                    if pa != pb:
                        parent[max(pa, pb)] = min(pa, pb)
        roots = np.array([find(i) for i in range(n + 1)])
        lab = roots[lab]
        uniq = np.unique(lab[lab > 0])
        remap = np.zeros(lab.max() + 1, dtype=np.int64)
        remap[uniq] = np.arange(1, uniq.size + 1)
        lab, n = remap[lab], int(uniq.size)
    return lab, n


def group(screening: ScreeningResult, ctx: StageContext) -> list[CandidateArea]:
    profile = ctx.profile
    settings = ctx.settings
    geo = _geometry(ctx.grid)
    li = screening.land
    h, w = geo["grid_shape"]
    cell = geo["cell_deg"]
    min_score = float(settings["screen_min_score"])
    max_area = float(settings["max_area_km2"])
    keep = screening.survivors & (np.nan_to_num(screening.screening_score, nan=-1) >= min_score)
    idx_of = np.full((h, w), -1, dtype=np.int64)
    idx_of[li.rows, li.cols] = np.arange(li.rows.size)
    mask = np.zeros((h, w), bool)
    mask[li.rows[keep], li.cols[keep]] = True
    lab, n = _labels(mask, geo["wrap_lon"])

    # split large components on a fixed tile grid aligned to the cells
    side_km = math.sqrt(max_area)
    tile_r = max(1, round(side_km / (cell * KM_PER_DEG)))
    parts: list[np.ndarray] = []  # each: land-vector indices of one candidate area
    comp_cells = ndimage.find_objects(lab)
    for k, sl in enumerate(comp_cells, start=1):
        if sl is None:
            continue
        rr, cc = np.nonzero(lab[sl] == k)
        rr, cc = rr + sl[0].start, cc + sl[1].start
        members = idx_of[rr, cc]
        if li.area_km2[members].sum() <= max_area:
            parts.append(members)
            continue
        lat_c = float(np.mean(li.lat[members]))
        tile_c = max(
            1, round(side_km / (cell * KM_PER_DEG * max(math.cos(math.radians(lat_c)), 1e-3)))
        )
        tiles: dict[tuple[int, int], list[int]] = {}
        for m, r, c in zip(members, rr, cc, strict=True):
            tiles.setdefault((int(r) // tile_r, int(c) // tile_c), []).append(int(m))
        parts.extend(np.array(v) for _, v in sorted(tiles.items()))

    crit = grid_criteria(profile)
    slope = next((c for c in crit if c.quantity == "slope_p90"), None)
    areas, hints = [], {}
    for members in parts:
        ss = screening.screening_score[members]
        order = np.lexsort((li.cols[members], li.rows[members], -ss))  # score ↓, north, west
        rep = int(members[order[0]])
        lat, lon = float(li.lat[rep]), float(li.lon[rep])
        wts = li.area_km2[members]
        half = cell / 2
        aid = f"{profile.profile_id}-{lat:.2f}_{lon:.2f}"
        grid_scores = {
            c.id: score(
                c, float(screening.footprint[c.id][rep]), pct=screening.percentiles.get(c.id)
            )
            for c in crit
        }
        areas.append(
            CandidateArea(
                area_id=aid,
                cell_idx=np.asarray(members, dtype=np.int64),
                n_cells=int(members.size),
                area_km2=float(wts.sum()),
                bbox=(
                    float(li.lon[members].min() - half),
                    float(li.lat[members].min() - half),
                    float(li.lon[members].max() + half),
                    float(li.lat[members].max() + half),
                ),
                centroid=(
                    float(np.average(li.lat[members], weights=wts)),
                    float(np.average(li.lon[members], weights=wts)),
                ),
                representative=(lat, lon),
                rep_idx=rep,
                footprint=(lat, lon, profile.radius_km),
                grid_scores=grid_scores,
                refined={},
            )
        )
        if slope is not None and np.isfinite(screening.footprint[slope.id][rep]):
            hints[aid] = float(screening.footprint[slope.id][rep])
    areas.sort(key=lambda a: a.area_id)
    initial_bounds(areas, ctx, hints=hints)
    log.info(
        "grouping: %d components -> %d candidate areas (max %.0f km²)", n, len(areas), max_area
    )
    return areas
