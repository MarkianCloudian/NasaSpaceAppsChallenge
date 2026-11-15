"""Final scoring, ranking and run record (plan E5, task T053).

`rank(areas, screening, ctx, refinement=...) -> dict` (valid against results.schema.json):
  1. per area, merge the grid-scale footprint values at the representative cell
     (`screening.footprint[criterion_id][rep_idx]`, scored with the population percentiles
     for normalized criteria) with the refinement results over the same footprint
     (refinement replaces grid for the same criterion); record `scale_used` and `footprint`;
  2. score every criterion (scoring.rules) and aggregate with veto (scoring.aggregate);
  3. status: veto -> `rejected` (+ `rejected_by`, at any refinement level); not fully refined
     -> `screened_only`;
     confidence < profile.min_confidence -> `insufficient_data`; else `ranked`;
     ranked by overall score desc, confidence desc, area_id;
  4. analogy limits: every not_comparable criterion, every normalized criterion, the
     east-west baseline of grid slope criteria at the area's latitude (research D-020) and
     every UNKNOWN criterion;
  5. writes `results.json` (with embedded `run_record`), `results.csv` (one row per
     candidate × criterion) and `run_record.json` into `ctx.stage_dir`.

`exit_code(results)`: 7 when nothing is ranked, 6 when a criterion is UNKNOWN because its
source failed (refinement result without source and coverage), else 0 (contracts/cli.md).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import errors
from .config import validate_against
from .scoring.aggregate import aggregate
from .scoring.rules import score
from .storage import fingerprint
from .types import CandidateArea, Criterion, CriterionScore, Profile, ScreeningResult

CSV_FIELDS = [
    "area_id",
    "rank",
    "status",
    "overall_score",
    "confidence",
    "criterion_id",
    "state",
    "relative",
    "earth_value",
    "unit",
    "target",
    "deviation",
    "deviation_ratio",
    "score",
    "weight_effective",
    "scale_used",
    "source_id",
    "note",
]
REFINEMENT_KEYS = ("stop", "proven_top", "terrain_areas", "mineral_areas", "emit_covered_areas")


def _clean(v: Any) -> Any:
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python, recursively."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _grid_value(c: Criterion, area: CandidateArea, screening: ScreeningResult | None):
    if screening is not None and c.id in screening.footprint:
        return float(screening.footprint[c.id][area.rep_idx])
    return None


def _criterion_results(area, profile, screening, raw) -> tuple[dict, list[dict]]:
    scores: dict[str, CriterionScore] = {}
    rows: list[dict] = []
    pct = screening.percentiles if screening is not None else {}
    for c in profile.criteria:
        note = ""
        if c.comparison == "not_comparable":
            cs, value, scale, source = (
                CriterionScore(None, None, None, "not_comparable"),
                None,
                None,
                None,
            )
        elif c.id in raw or c.id in area.refined:
            r = raw.get(c.id, {})
            value, source, scale = r.get("value"), r.get("source_id"), "refinement"
            cs = area.refined.get(c.id) or score(c, math.nan if value is None else value)
            if cs.state == "unknown":
                note = (
                    "source failed"
                    if r and r.get("source_id") is None and r.get("coverage") is None
                    else "no data"
                )
        else:
            value, scale = _grid_value(c, area, screening), "grid"
            source = c.earth_sources[0] if c.earth_sources else None
            if value is not None:
                cs = score(c, value, pct=pct.get(c.id))
            else:
                cs = area.grid_scores.get(c.id) or CriterionScore(None, None, None, "unknown")
            if cs.state == "unknown":
                note = "no data"
        scores[c.id] = cs
        rows.append(
            {"c": c, "cs": cs, "value": value, "scale": scale, "source": source, "note": note}
        )
    return scores, rows


def _limits(area, profile: Profile, rows, population: str) -> list[str]:
    out = []
    lat = area.footprint[0]
    for r in rows:
        c, cs = r["c"], r["cs"]
        if c.comparison == "not_comparable":
            out.append(f"not reproducible on Earth: {c.id} ({c.quantity})")
        elif c.comparison == "normalized":
            out.append(f"relative to {population} on Earth, not absolute: {c.id} ({c.quantity})")
        if (
            c.quantity.startswith("slope")
            and c.evaluation_scale in ("grid", "both")
            and c.baseline_m
        ):
            ew = c.baseline_m * math.cos(math.radians(lat))
            out.append(
                f"{c.id}: grid baseline is {c.baseline_m:g} m north-south but {ew:.0f} m east-west "
                f"at {lat:.1f}° (geographic 30″ grid, research D-020)"
            )
        if cs.state == "unknown":
            out.append(f"no Earth data: {c.id} ({r['note'] or 'unknown'})")
    return out


def rank(
    areas: list[CandidateArea],
    screening: ScreeningResult | None,
    ctx,
    refinement: Mapping[str, Any] | None = None,
    stages: list[dict] | None = None,
    stage_fingerprints: Mapping[str, str] | None = None,
    started_at: str | None = None,
    sources_config: Mapping[str, Any] | None = None,
) -> dict:
    t0 = time.monotonic()
    started_at = started_at or dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    profile: Profile = ctx.profile
    refinement = dict(refinement or {})
    raw_all = refinement.get("values", {})
    population = screening.population if screening is not None else ("eligible", 0)
    weights = profile.weights
    candidates = []
    used_sources: set[str] = set()
    for area in areas:
        scores, rows = _criterion_results(area, profile, screening, raw_all.get(area.area_id, {}))
        agg = aggregate(scores, profile)
        known_w = sum(float(weights.get(r["c"].id, 0.0)) for r in rows if r["cs"].state == "known")
        if agg.rejected_by:  # a veto rejects the area whatever its refinement level
            status = "rejected"
        elif area.refinement_level != "full":
            status = "screened_only"
        elif agg.overall is None or agg.confidence + 1e-12 < profile.min_confidence:
            status = "insufficient_data"
        else:
            status = "ranked"
        results = []
        for r in rows:
            c, cs = r["c"], r["cs"]
            if r["source"]:
                used_sources.add(r["source"])
            w = float(weights.get(c.id, 0.0))
            results.append(
                {
                    "criterion_id": c.id,
                    "state": cs.state,
                    "relative": bool(cs.relative),
                    "earth_value": r["value"],
                    "unit": c.unit,
                    "target": dict(c.target) if c.target else {},
                    "deviation": cs.deviation,
                    "deviation_ratio": cs.deviation_ratio,
                    "score": cs.score,
                    "weight_effective": (w / known_w)
                    if cs.state == "known" and known_w > 0
                    else None,
                    "scale_used": r["scale"],
                    "source_id": r["source"],
                    "note": r["note"],
                }
            )
        lat, lon, radius = area.footprint
        candidates.append(
            {
                "area_id": area.area_id,
                "rank": None,
                "status": status,
                "centroid": {"lat": area.centroid[0], "lon": area.centroid[1]},
                "representative": {"lat": area.representative[0], "lon": area.representative[1]},
                "n_cells": int(area.n_cells),
                "area_km2": float(area.area_km2),
                "bbox": list(area.bbox),
                "overall_score": agg.overall if status in ("ranked", "insufficient_data") else None,
                "confidence": agg.confidence,
                "limiting_criterion": agg.limiting,
                "rejected_by": agg.rejected_by,
                "analogy_limits": _limits(area, profile, rows, population[0]),
                "label": None,
                "known_site": None,
                "results": results,
                "footprint": {"lat": lat, "lon": lon, "radius_km": radius},
                "upper_bound": area.upper_bound,
                "refinement_level": area.refinement_level,
            }
        )
    ranked = sorted(
        (c for c in candidates if c["status"] == "ranked"),
        key=lambda c: (-c["overall_score"], -c["confidence"], c["area_id"]),
    )
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
    order = {c["area_id"]: i for i, c in enumerate(ranked)}
    candidates.sort(key=lambda c: (order.get(c["area_id"], len(order)), c["status"], c["area_id"]))

    grid_id = ctx.grid.grid_id if getattr(ctx, "grid", None) is not None else "none"
    today = dt.date.today().isoformat()
    entries = {e["source_id"]: e for e in (sources_config or {}).get("sources", [])}
    sources = [
        {
            "source_id": s,
            "dataset_version": str(entries.get(s, {}).get("dataset_version", "unknown")),
            "accessed": today,
        }
        for s in sorted(used_sources)
    ]
    counts_in = dict(screening.counts) if screening is not None else {}
    fp = Path(ctx.stage_dir).name  # stage directories are named by their fingerprint (D-011)
    if not re.fullmatch(r"[0-9a-f]{16}", fp):
        fp = fingerprint({"stage": "rank", "profile": profile.content_hash, "grid": grid_id})
    run_record = {
        "run_id": fingerprint(
            {
                "profile": profile.content_hash,
                "grid": grid_id,
                "settings": _clean(dict(ctx.settings)),
            }
        ),
        "profile": {
            "id": profile.profile_id,
            "version": profile.version,
            "content_hash": profile.content_hash,
        },
        "grid_id": grid_id,
        "settings": dict(ctx.settings),
        "sources": sources,
        "started_at": started_at,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "stages": stages
        or [
            {
                "name": "rank",
                "status": "complete",
                "seconds": round(time.monotonic() - t0, 3),
                "fingerprint": fp,
            }
        ],
        "counts": {
            "evaluated_cells": int(counts_in.get("evaluated", 0)),
            "rejected_by_constraint": int(counts_in.get("rejected_by_constraint", 0)),
            "rejected_by_criterion": dict(counts_in.get("rejected_by_criterion", {})),
            "areas": len(areas),
            "refined": sum(1 for a in areas if a.refinement_level != "none"),
            "insufficient_data": sum(1 for c in candidates if c["status"] == "insufficient_data"),
            "ranked": len(ranked),
        },
        "placeholder_values": any(c.value_status == "placeholder" for c in profile.criteria),
        "dedup_applied": False,
        "percentile_population": {"name": population[0], "cells": int(population[1])},
        "stage_fingerprints": dict(stage_fingerprints or {"rank": fp}),
        "refinement": {k: refinement[k] for k in REFINEMENT_KEYS if k in refinement}
        or {"stop": "skipped", "proven_top": 0, "terrain_areas": 0, "mineral_areas": 0},
    }
    results = _clean({"run_record": run_record, "candidates": candidates})
    errs = validate_against(results, "results.schema.json", "results.json")
    if errs:
        raise errors.ValidationError(
            "results.json does not match its schema:\n  " + "\n  ".join(errs)
        )
    _write(Path(ctx.stage_dir), results)
    return results


def _write(d: Path, results: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (d / "run_record.json").write_text(
        json.dumps(results["run_record"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with open(d / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for c in results["candidates"]:
            for r in c["results"]:
                row = {
                    k: c[k] for k in ("area_id", "rank", "status", "overall_score", "confidence")
                }
                row.update({k: r.get(k) for k in CSV_FIELDS if k in r})
                for k in ("earth_value", "target"):
                    if isinstance(row.get(k), (dict, list)):
                        row[k] = json.dumps(row[k], ensure_ascii=False)
                w.writerow(row)


def exit_code(results: dict) -> int:
    if not any(c["status"] == "ranked" for c in results["candidates"]):
        return errors.NO_CANDIDATES
    for c in results["candidates"]:
        if any(r["state"] == "unknown" and r.get("note") == "source failed" for r in c["results"]):
            return errors.PARTIAL_RESULT
    return errors.OK
