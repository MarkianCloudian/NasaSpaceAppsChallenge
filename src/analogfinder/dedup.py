"""Deduplication against known Earth analogs (plan H1, spec US5, SC-011, task T081).

`dedup(results, ctx) -> dict` returns a copy of `results` with every candidate labelled:
  - distance from a candidate area to a relevant known site (same body/purpose filter as
    calibration, T077) = great-circle (haversine, Earth radius 6371 km) distance from the site to
    the nearest of the area's cells, or to its representative point when the cells are not
    available;
  - within the site's `radius_km` (default `settings.known_radius_default_km`) →
    `label: "known_analog"`, `known_site: <site name>` (the nearest such site); otherwise
    `label: "new_candidate"`, `known_site: null`;
  - candidates are never removed or reordered; `run_record.dedup_applied = true` and
    `run_record.dedup` = {new_candidates, known_analogs, sites_checked, note}: counts among the
    ranked candidates, and when fewer than 3 ranked candidates are new, why (SC-011).
Writes `results.dedup.json` (valid against results.schema.json) into `ctx.stage_dir`;
`results.json` is never overwritten.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from . import config, errors, stage_io
from .calibrate import relevant_sites
from .types import CandidateArea, LandIndex, StageContext

log = logging.getLogger("analogfinder.dedup")

EARTH_R_KM = 6371.0
MIN_NEW = 3  # SC-011
DEDUP_FILE = "results.dedup.json"


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _points(cand: Mapping[str, Any], cells: Mapping[str, np.ndarray], land: LandIndex | None):
    idx = cells.get(cand["area_id"])
    if idx is not None and land is not None and len(idx):
        return land.lat[idx], land.lon[idx]
    rep = cand["representative"]
    return np.array([rep["lat"]]), np.array([rep["lon"]])


def dedup(
    results: dict,
    ctx: StageContext,
    *,
    areas: Sequence[CandidateArea] | None = None,
    land: LandIndex | None = None,
    known: Mapping[str, Any] | None = None,
    write: bool = True,
) -> dict:
    profile = ctx.profile
    if known is None:
        known = config.load_known_analogs(ctx.config_dir)
    sites = relevant_sites(known, profile)
    default_r = float(ctx.settings["known_radius_default_km"])
    cells = {a.area_id: np.asarray(a.cell_idx, dtype=np.int64) for a in areas or ()}

    out = copy.deepcopy(results)
    for cand in out["candidates"]:
        lat, lon = _points(cand, cells, land)
        best = None  # (distance, site name)
        for s in sites:
            d = float(np.min(haversine_km(s["lat"], s["lon"], lat, lon)))
            if d <= float(s.get("radius_km", default_r)) and (best is None or d < best[0]):
                best = (d, s["name"])
        cand["label"] = "known_analog" if best else "new_candidate"
        cand["known_site"] = best[1] if best else None

    ranked = [c for c in out["candidates"] if c["status"] == "ranked"]
    n_new = sum(c["label"] == "new_candidate" for c in ranked)
    n_known = len(ranked) - n_new
    note = None
    if n_new < MIN_NEW:
        if len(ranked) < MIN_NEW:
            note = (
                f"only {len(ranked)} area(s) ranked for this profile, fewer than {MIN_NEW}; "
                "see run_record.counts and refinement for where candidates were lost"
            )
        else:
            note = (
                f"{n_known} of {len(ranked)} ranked areas lie within the radius of a known "
                f"analog site, leaving {n_new} new candidate(s)"
            )
    rr = out["run_record"]
    rr["dedup_applied"] = True
    rr["dedup"] = {
        "new_candidates": n_new,
        "known_analogs": n_known,
        "sites_checked": [s["site_id"] for s in sites],
        "note": note,
    }
    log.info("dedup: %d ranked, %d new, %d known analogs", len(ranked), n_new, n_known)
    if note:
        log.warning("dedup: fewer than %d new candidates: %s", MIN_NEW, note)
    if write:
        errs = config.validate_against(out, "results.schema.json", DEDUP_FILE)
        if errs:
            raise errors.ValidationError(
                f"{DEDUP_FILE} does not match its schema:\n  " + "\n  ".join(errs)
            )
        d = Path(ctx.stage_dir)
        d.mkdir(parents=True, exist_ok=True)
        stage_io.write_json(d / DEDUP_FILE, out)
    return out
