"""Shared types, exactly as specs/001-earth-analog-finder/contracts/internal-api.md (task T007).

Every module imports its shared types from here. A change to these types is made in the
contract file in the same pull request.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

if TYPE_CHECKING:
    from .scoring.percentile import Percentile
    from .sources.base import SourceRegistry

State = Literal["known", "unknown", "not_comparable"]
Statistic = Literal["mean", "median", "max", "min", "p90", "p10", "fraction_true"]


@dataclass(frozen=True, slots=True)
class Criterion:
    """One entry of profile.criteria (profile.schema.json $defs.criterion)."""

    id: str
    category: str
    quantity: str
    statistic: str
    unit: str
    evaluation_scale: Literal["grid", "refinement", "both"]
    comparison: Literal["absolute", "normalized", "not_comparable"]
    scoring_rule: str | None
    target: Mapping[str, Any] | None
    tolerance: Mapping[str, float] | None
    veto: float | None
    footprint_statistic: Statistic | None
    baseline_m: float | None
    value_status: Literal["measured", "placeholder"]
    uncertainty: Mapping[str, float] | None
    class_map: str | None
    earth_sources: tuple[str, ...]
    raw: Mapping[str, Any]  # full JSON for extras

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Criterion:
        earth = (d.get("sources") or {}).get("earth") or []
        return cls(
            id=d["id"],
            category=d["category"],
            quantity=d["quantity"],
            statistic=d["statistic"],
            unit=d["unit"],
            evaluation_scale=d["evaluation_scale"],
            comparison=d["comparison"],
            scoring_rule=d.get("scoring_rule"),
            target=d.get("target"),
            tolerance=d.get("tolerance"),
            veto=d.get("veto"),
            footprint_statistic=d.get("footprint_statistic"),
            baseline_m=d.get("baseline_m"),
            value_status=d["value_status"],
            uncertainty=d.get("uncertainty"),
            class_map=d.get("class_map"),
            earth_sources=tuple(str(e) for e in earth),  # schema: list of source_id strings
            raw=d,
        )


@dataclass(frozen=True, slots=True)
class Profile:
    """A FROZEN profile (profiles/frozen/<id>@<version>.json)."""

    profile_id: str
    version: str
    body: str
    purpose: str
    site_lat: float
    site_lon: float
    radius_km: float
    search_constraints: Mapping[str, Any]
    min_confidence: float
    percentile_population: Literal["eligible", "all_land", "ice_free_land"]
    criteria: tuple[Criterion, ...]
    weights: Mapping[str, float]  # criterion_id -> weight
    content_hash: str

    @property
    def ref(self) -> str:
        return f"{self.profile_id}@{self.version}"

    @classmethod
    def from_frozen_json(cls, d: Mapping[str, Any]) -> Profile:
        site = d["reference_site"]
        return cls(
            profile_id=d["profile_id"],
            version=d["version"],
            body=d["body"],
            purpose=d["purpose"],
            site_lat=float(site["lat"]),
            site_lon=float(site["lon"]),
            radius_km=float(site["radius_km"]),
            search_constraints=d.get("search_constraints", {}),
            min_confidence=float(d.get("min_confidence", 0.0)),
            percentile_population=d.get("percentile_population", "eligible"),
            criteria=tuple(Criterion.from_json(c) for c in d["criteria"]),
            weights=dict(d.get("weights", {})),
            content_hash=d.get("content_hash", ""),
        )


@dataclass(frozen=True, slots=True)
class CriterionScore:
    score: float | None
    deviation: float | None
    deviation_ratio: float | None
    state: State
    relative: bool = False


@dataclass(frozen=True, slots=True)
class Aggregate:
    overall: float | None
    confidence: float
    limiting: str | None
    rejected_by: str | None


@dataclass(frozen=True, slots=True)
class LandIndex:
    """Eligible land cells of one grid version."""

    rows: np.ndarray  # int32
    cols: np.ndarray  # int32
    lat: np.ndarray  # float64
    lon: np.ndarray  # float64
    area_km2: np.ndarray  # float64


@dataclass(frozen=True, slots=True)
class GridVersion:
    grid_id: str
    path: Path
    manifest: Mapping[str, Any]

    def layer(self, layer_id: str) -> np.ndarray:  # full raster, float32
        raise NotImplementedError("GridVersion.layer is implemented by the grid build task")

    def land_index(self) -> LandIndex:
        raise NotImplementedError("GridVersion.land_index is implemented by the grid build task")

    def land_vector(self, layer_id: str) -> np.ndarray:  # aligned to land_index()
        raise NotImplementedError("GridVersion.land_vector is implemented by the grid build task")


@dataclass(frozen=True, slots=True)
class FetchResult:
    path: Path
    source_id: str  # source that actually served the data
    coverage: float | None


@dataclass(slots=True)
class StageContext:
    stage: str
    stage_dir: Path
    data_dir: Path
    config_dir: Path
    settings: Mapping[str, Any]
    profile: Profile | None
    grid: GridVersion | None
    sources: SourceRegistry
    log: logging.Logger


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    land: LandIndex
    survivors: np.ndarray  # bool, aligned to land
    screening_score: np.ndarray  # float, NaN where rejected
    footprint: Mapping[str, np.ndarray]  # criterion_id -> footprint values (land-aligned)
    percentiles: Mapping[str, Percentile]  # normalized criteria only
    population: tuple[str, int]  # (name, cells)
    counts: Mapping[str, Any]  # evaluated, rejected_by_constraint, rejected_by_criterion


@dataclass(slots=True)
class CandidateArea:
    area_id: str
    cell_idx: np.ndarray  # indices into LandIndex
    n_cells: int
    area_km2: float
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    representative: tuple[float, float]
    rep_idx: int
    footprint: tuple[float, float, float]  # lat, lon, radius_km
    grid_scores: dict[str, CriterionScore]  # footprint values at rep cell, scored
    refined: dict[str, CriterionScore]  # filled by refinement
    upper_bound: float | None = None
    refinement_level: Literal["none", "terrain", "full"] = "none"
    status: Literal["ranked", "insufficient_data", "rejected", "screened_only"] = "screened_only"
    aggregate: Aggregate | None = None


@dataclass(frozen=True, slots=True)
class GroupResult:
    """One refinement group for one area."""

    group: Literal["terrain", "mineral"]
    values: Mapping[str, Any]  # criterion_id -> value
    source_id: str | None
    coverage: float | None
