"""Screening of every land cell against the frozen profile (research D-013, D-017, D-021, T048).

`run(ctx) -> ScreeningResult` for `ctx.profile` on `ctx.grid`:
  1. footprint values (T046 `focal_many`) of every grid-scale criterion's layer, with the
     criterion's `footprint_statistic`, over `reference_site.radius_km`, plus the footprint
     mean of the land-cover fractions the constraints need. Layers are found through
     `config/layers.json` (output `quantity` or `layer_id`). Raw cell values are never compared
     with targets: only footprint values are scored;
  2. hard search constraints: latitude range (`search_constraints.lat_range`), every
     `max_landcover_fraction` class on the footprint mean of `lc_frac_<class>`,
     `min_barren_fraction`; cells whose constraint layers are NaN fail (cannot be verified);
  3. percentiles (T032) of every normalized criterion over `percentile_population` (D-021:
     `eligible` = cells passing the hard constraints, before vetoes), area-weighted;
  4. grid-scale vetoes in order of measured selectivity (largest fraction removed from the
     current survivors first), scored with the vectorised rules (T028); UNKNOWN never vetoes;
  5. screening score = weighted geometric mean over the grid-scale criteria (T030, renormalised
     over known ones); NaN where rejected.
Writes `screening.json` (counts) into `ctx.stage_dir`; on the global grid also
`footprint/<criterion_id>.tif`, `screening_score.tif`, `survivors.tif`. The land-aligned
vectors themselves are stored by the pipeline (stage_io).

Grid geometry comes from the grid manifest `cell` entry (size_deg, width, height, origin), so
small test grids work the same way as the global 0.05° grid.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from . import config, stage_io
from .footprint import focal_many
from .scoring.aggregate import aggregate_arrays
from .scoring.percentile import Percentile, population_mask
from .scoring.rules import score_array
from .types import Criterion, Profile, ScreeningResult, StageContext

log = logging.getLogger("analogfinder.screening")


def grid_criteria(profile: Profile) -> list[Criterion]:
    return [
        c
        for c in profile.criteria
        if c.evaluation_scale in ("grid", "both") and c.comparison != "not_comparable"
    ]


def layer_for(quantity: str, layers: dict) -> str:
    for entry in layers["layers"]:
        for o in entry["outputs"]:
            if quantity in (o.get("quantity"), o.get("layer_id")):
                return o["layer_id"]
    raise config.ConfigError(f"no layers.json output provides quantity {quantity!r}")


def _geometry(grid) -> dict:
    cell = (getattr(grid, "manifest", None) or {}).get("cell") or {}
    size = float(cell.get("size_deg", 0.05))
    width, height = int(cell.get("width", 7200)), int(cell.get("height", 3600))
    origin = cell.get("origin", [-180.0, 90.0])
    return {
        "cell_deg": size,
        "lat_top": float(origin[1]),
        "grid_shape": (height, width),
        "wrap_lon": abs(width * size - 360.0) < 1e-6,
        "global": (width, height) == (7200, 3600),
    }


def run(ctx: StageContext) -> ScreeningResult:
    profile: Profile = ctx.profile
    grid = ctx.grid
    settings = ctx.settings
    layers = config.load_layers(ctx.config_dir)
    sc = profile.search_constraints or {}
    geo = _geometry(grid)
    land = grid.land_index()
    n = int(land.rows.size)
    radius = profile.radius_km
    min_valid = float(settings["footprint"]["min_valid_fraction"])
    crit = grid_criteria(profile)

    # 1. footprint values in one pass (criteria + land-cover fractions for the constraints)
    lc_classes = sorted(
        set(sc.get("max_landcover_fraction") or {})
        | ({"barren"} if "min_barren_fraction" in sc else set())
        | ({"snow_ice"} if profile.percentile_population == "ice_free_land" else set())
    )
    jobs = {
        c.id: (grid.land_vector(layer_for(c.quantity, layers)), c.footprint_statistic) for c in crit
    }
    for k in lc_classes:
        jobs[f"lc:{k}"] = (grid.land_vector(f"lc_frac_{k}"), "mean")
    fp = focal_many(
        jobs,
        land,
        radius,
        min_valid,
        cell_deg=geo["cell_deg"],
        lat_top=geo["lat_top"],
        grid_shape=geo["grid_shape"],
        wrap_lon=geo["wrap_lon"],
    )
    footprint = {c.id: fp[c.id] for c in crit}

    # 2. hard constraints
    ok = np.ones(n, bool)
    lat_range = sc.get("lat_range")
    if lat_range:
        ok &= (land.lat >= min(lat_range)) & (land.lat <= max(lat_range))
    for k, mx in (sc.get("max_landcover_fraction") or {}).items():
        v = fp[f"lc:{k}"]
        ok &= np.isfinite(v) & (v <= mx)
    if "min_barren_fraction" in sc:
        v = fp["lc:barren"]
        ok &= np.isfinite(v) & (v >= sc["min_barren_fraction"])
    rejected_by_constraint = int(n - ok.sum())

    # 3. percentiles over the reference population (D-021)
    pop = population_mask(
        profile.percentile_population,
        np.ones(n, bool),
        constraints_mask=ok,
        snow_ice_footprint=fp.get("lc:snow_ice"),
    )
    percentiles = {
        c.id: Percentile.build(footprint[c.id][pop], land.area_km2[pop])
        for c in crit
        if c.comparison == "normalized"
    }

    # 4. vectorised scores and vetoes by measured selectivity
    scores = {c.id: score_array(c, footprint[c.id], pct=percentiles.get(c.id))[0] for c in crit}
    alive = ok.copy()
    rejected_by_criterion: dict[str, int] = {}
    vetoes = {c.id: c.veto for c in crit if c.veto is not None}
    while vetoes:
        fails = {
            cid: alive & np.isfinite(scores[cid]) & (scores[cid] < v) for cid, v in vetoes.items()
        }
        cid = max(sorted(fails), key=lambda k: int(fails[k].sum()))
        removed = int(fails[cid].sum())
        rejected_by_criterion[cid] = removed
        alive &= ~fails[cid]
        del vetoes[cid]

    # 5. screening score over the grid-scale criteria
    overall, _ = aggregate_arrays(scores, profile)
    screening_score = np.where(alive, overall, np.nan)
    survivors = alive & np.isfinite(screening_score)
    counts = {
        "evaluated": n,
        "evaluated_cells": n,
        "rejected_by_constraint": rejected_by_constraint,
        "rejected_by_criterion": rejected_by_criterion,
        "survivors": int(survivors.sum()),
    }
    log.info(
        "screening: %d land cells, %d fail constraints, vetoes %s, %d survive",
        n,
        rejected_by_constraint,
        rejected_by_criterion,
        int(survivors.sum()),
    )

    d = Path(ctx.stage_dir)
    d.mkdir(parents=True, exist_ok=True)
    stage_io.write_json(
        d / "screening.json",
        {
            "population": [profile.percentile_population, int(pop.sum())],
            "counts": counts,
        },
    )
    if geo["global"]:
        _write_rasters(d, land, footprint, screening_score, survivors)
    return ScreeningResult(
        land=land,
        survivors=survivors,
        screening_score=screening_score,
        footprint=footprint,
        percentiles=percentiles,
        population=(profile.percentile_population, int(pop.sum())),
        counts=counts,
    )


def _write_rasters(d: Path, land, footprint, screening_score, survivors) -> None:
    from .grid import cells

    def raster(vec):
        a = np.full((cells.N_ROWS, cells.N_COLS), np.nan, dtype="float32")
        a[land.rows, land.cols] = vec
        return a

    (d / "footprint").mkdir(parents=True, exist_ok=True)
    for cid, v in footprint.items():
        cells.write_layer(d / "footprint" / f"{cid}.tif", raster(v))
    cells.write_layer(d / "screening_score.tif", raster(screening_score))
    cells.write_layer(d / "survivors.tif", raster(survivors.astype("float32")))
