"""On-disk form of the data handed from one stage to the next (research D-011, task T054).

A stage reused from the cache must give the next stage exactly what a fresh run would, so the
pipeline stores and reloads:

- the screening result (`screen` stage): `land.npz` (LandIndex), `survivors.npy`,
  `screening_score.npy`, `footprint/<criterion_id>.npy`, `percentiles/<criterion_id>.json`,
  `screening.json` (population, counts). Per-cell data stay land-aligned 1-D vectors
  (contracts/internal-api.md), not full-grid rasters;
- candidate areas (`screen` after grouping, `refine` after the scheduler): `areas.json`;
- the refinement summary (`refine`): `refinement.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .scoring.percentile import Percentile
from .types import Aggregate, CandidateArea, CriterionScore, LandIndex, ScreeningResult


def write_json(path: Path, data: Any) -> None:
    Path(path).write_text(
        json.dumps(data, indent=1, ensure_ascii=False, default=_default) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


# --- screening ------------------------------------------------------------------------------


def save_screening(d: Path, s: ScreeningResult) -> None:
    d = Path(d)
    (d / "footprint").mkdir(parents=True, exist_ok=True)
    (d / "percentiles").mkdir(exist_ok=True)
    np.savez(
        d / "land.npz",
        rows=s.land.rows,
        cols=s.land.cols,
        lat=s.land.lat,
        lon=s.land.lon,
        area_km2=s.land.area_km2,
    )
    np.save(d / "survivors.npy", np.asarray(s.survivors, bool))
    np.save(d / "screening_score.npy", np.asarray(s.screening_score, "float64"))
    for cid, v in s.footprint.items():
        np.save(d / "footprint" / f"{cid}.npy", np.asarray(v, "float64"))
    for cid, p in s.percentiles.items():
        write_json(d / "percentiles" / f"{cid}.json", p.to_json())
    write_json(d / "screening.json", {"population": list(s.population), "counts": s.counts})


def load_screening(d: Path) -> ScreeningResult:
    d = Path(d)
    z = np.load(d / "land.npz")
    land = LandIndex(z["rows"], z["cols"], z["lat"], z["lon"], z["area_km2"])
    meta = read_json(d / "screening.json")
    return ScreeningResult(
        land=land,
        survivors=np.load(d / "survivors.npy"),
        screening_score=np.load(d / "screening_score.npy"),
        footprint={p.stem: np.load(p) for p in sorted((d / "footprint").glob("*.npy"))},
        percentiles={
            p.stem: Percentile.from_json(read_json(p))
            for p in sorted((d / "percentiles").glob("*.json"))
        },
        population=(meta["population"][0], int(meta["population"][1])),
        counts=meta["counts"],
    )


# --- candidate areas ------------------------------------------------------------------------


def _cs(c: CriterionScore) -> dict:
    return {
        "score": c.score,
        "deviation": c.deviation,
        "deviation_ratio": c.deviation_ratio,
        "state": c.state,
        "relative": c.relative,
    }


def _cs_back(d: dict) -> CriterionScore:
    return CriterionScore(
        d["score"], d["deviation"], d["deviation_ratio"], d["state"], d.get("relative", False)
    )


def area_to_json(a: CandidateArea) -> dict:
    return {
        "area_id": a.area_id,
        "cell_idx": np.asarray(a.cell_idx).tolist(),
        "n_cells": a.n_cells,
        "area_km2": a.area_km2,
        "bbox": list(a.bbox),
        "centroid": list(a.centroid),
        "representative": list(a.representative),
        "rep_idx": int(a.rep_idx),
        "footprint": list(a.footprint),
        "grid_scores": {k: _cs(v) for k, v in a.grid_scores.items()},
        "refined": {k: _cs(v) for k, v in a.refined.items()},
        "upper_bound": a.upper_bound,
        "refinement_level": a.refinement_level,
        "status": a.status,
        "aggregate": None
        if a.aggregate is None
        else {
            "overall": a.aggregate.overall,
            "confidence": a.aggregate.confidence,
            "limiting": a.aggregate.limiting,
            "rejected_by": a.aggregate.rejected_by,
        },
    }


def area_from_json(d: dict) -> CandidateArea:
    agg = d.get("aggregate")
    return CandidateArea(
        area_id=d["area_id"],
        cell_idx=np.asarray(d["cell_idx"], dtype=np.int64),
        n_cells=int(d["n_cells"]),
        area_km2=float(d["area_km2"]),
        bbox=tuple(d["bbox"]),
        centroid=tuple(d["centroid"]),
        representative=tuple(d["representative"]),
        rep_idx=int(d["rep_idx"]),
        footprint=tuple(d["footprint"]),
        grid_scores={k: _cs_back(v) for k, v in d["grid_scores"].items()},
        refined={k: _cs_back(v) for k, v in d["refined"].items()},
        upper_bound=d.get("upper_bound"),
        refinement_level=d.get("refinement_level", "none"),
        status=d.get("status", "screened_only"),
        aggregate=None
        if agg is None
        else Aggregate(agg["overall"], agg["confidence"], agg["limiting"], agg["rejected_by"]),
    )


def save_areas(path: Path, areas: list[CandidateArea]) -> None:
    write_json(path, [area_to_json(a) for a in areas])


def load_areas(path: Path) -> list[CandidateArea]:
    return [area_from_json(d) for d in read_json(path)]
