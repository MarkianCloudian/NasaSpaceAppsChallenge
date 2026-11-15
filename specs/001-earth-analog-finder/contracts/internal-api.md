# Internal API Contract: module boundaries and shared types

Purpose: let several people (or agents) implement tasks in parallel without inventing
incompatible structures. Every module in `src/analogfinder/` MUST use the types and signatures
below. Shared types live in `src/analogfinder/types.py` (task T007) and nowhere else. Changing
this contract requires an edit to this file in the same pull request, reviewed by the team.

Field names follow `data-model.md` and the JSON Schemas in this folder; this file only fixes the
Python shape and the hand-over points between stages.

## Conventions

- Python 3.11, full type hints, `from __future__ import annotations`; dataclasses
  (`@dataclass(frozen=True, slots=True)`) for records; `numpy.ndarray` for arrays.
- Coordinates: latitude −90…90, longitude −180…180 (Earth); Mars/Moon longitudes as in the
  source, converted at load time. Distances in km unless a field says `_m`.
- Missing value = `float("nan")` (scalars) / `np.nan` (arrays). Never `None` inside arrays.
- Units are those declared in `config/layers.json` outputs and in each criterion's `unit`.
- **Land-cell vectors**: stage code works on 1-D arrays aligned to a `LandIndex` (one entry per
  eligible land cell), never on full 7200 × 3600 rasters, except the grid builders.
- Stages never build paths: they write only into `StageContext.stage_dir`.
- Errors: raise the classes in `errors.py` (`ConfigError`, `ValidationError`,
  `ProfileConflictError`, `SourceCheckError`); never `sys.exit` outside `cli.py`.
- Logging: `logging.getLogger("analogfinder.<module>")`; progress at INFO, details at DEBUG.

## Shared types (`types.py`)

```python
State = Literal["known", "unknown", "not_comparable"]
Statistic = Literal["mean", "median", "max", "min", "p90", "p10", "fraction_true"]

@dataclass(frozen=True, slots=True)
class Criterion:            # one entry of profile.criteria (profile.schema.json $defs.criterion)
    id: str; category: str; quantity: str; statistic: str; unit: str
    evaluation_scale: Literal["grid", "refinement", "both"]
    comparison: Literal["absolute", "normalized", "not_comparable"]
    scoring_rule: str | None; target: Mapping[str, Any] | None
    tolerance: Mapping[str, float] | None; veto: float | None
    footprint_statistic: Statistic | None; baseline_m: float | None
    value_status: Literal["measured", "placeholder"]
    uncertainty: Mapping[str, float] | None; class_map: str | None
    earth_sources: tuple[str, ...]; raw: Mapping[str, Any]   # full JSON for extras

@dataclass(frozen=True, slots=True)
class Profile:              # a FROZEN profile (profiles/frozen/<id>@<version>.json)
    profile_id: str; version: str; body: str; purpose: str
    site_lat: float; site_lon: float; radius_km: float
    search_constraints: Mapping[str, Any]; min_confidence: float
    percentile_population: Literal["eligible", "all_land", "ice_free_land"]
    criteria: tuple[Criterion, ...]; weights: Mapping[str, float]   # criterion_id -> weight
    content_hash: str
    @property
    def ref(self) -> str: ...                  # "id@version"

@dataclass(frozen=True, slots=True)
class CriterionScore:
    score: float | None; deviation: float | None; deviation_ratio: float | None
    state: State; relative: bool = False

@dataclass(frozen=True, slots=True)
class Aggregate:
    overall: float | None; confidence: float; limiting: str | None; rejected_by: str | None

@dataclass(frozen=True, slots=True)
class LandIndex:            # eligible land cells of one grid version
    rows: np.ndarray; cols: np.ndarray        # int32
    lat: np.ndarray; lon: np.ndarray; area_km2: np.ndarray   # float64

@dataclass(frozen=True, slots=True)
class GridVersion:
    grid_id: str; path: Path; manifest: Mapping[str, Any]
    def layer(self, layer_id: str) -> np.ndarray: ...        # full raster, float32
    def land_index(self) -> LandIndex: ...
    def land_vector(self, layer_id: str) -> np.ndarray: ...  # aligned to land_index()

@dataclass(frozen=True, slots=True)
class FetchResult:
    path: Path; source_id: str; coverage: float | None       # source that actually served data

@dataclass(slots=True)
class StageContext:
    stage: str; stage_dir: Path; data_dir: Path; config_dir: Path
    settings: Mapping[str, Any]; profile: Profile | None; grid: GridVersion | None
    sources: "SourceRegistry"; log: logging.Logger

@dataclass(frozen=True, slots=True)
class ScreeningResult:
    land: LandIndex; survivors: np.ndarray           # bool, aligned to land
    screening_score: np.ndarray                      # float, NaN where rejected
    footprint: Mapping[str, np.ndarray]              # criterion_id -> footprint values (land-aligned)
    percentiles: Mapping[str, "Percentile"]          # normalized criteria only
    population: tuple[str, int]                      # (name, cells)
    counts: Mapping[str, Any]                        # evaluated, rejected_by_constraint, rejected_by_criterion

@dataclass(slots=True)
class CandidateArea:
    area_id: str; cell_idx: np.ndarray               # indices into LandIndex
    n_cells: int; area_km2: float; bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]; representative: tuple[float, float]; rep_idx: int
    footprint: tuple[float, float, float]            # lat, lon, radius_km
    grid_scores: dict[str, CriterionScore]           # footprint values at rep cell, scored
    refined: dict[str, CriterionScore]               # filled by refinement
    upper_bound: float | None = None
    refinement_level: Literal["none", "terrain", "full"] = "none"
    status: Literal["ranked", "insufficient_data", "rejected", "screened_only"] = "screened_only"
    aggregate: Aggregate | None = None

@dataclass(frozen=True, slots=True)
class GroupResult:          # one refinement group for one area
    group: Literal["terrain", "mineral"]; values: Mapping[str, Any]   # criterion_id -> value
    source_id: str | None; coverage: float | None
```

## Module signatures (hand-over points)

| Module | Function | Input → output |
|---|---|---|
| `config` | `load_settings/sources/layers/purposes/known_analogs/mineral_classes(config_dir)` | path → validated dict (raises `ConfigError` listing all errors) |
| `storage` | `fingerprint(obj)`, `atomic_dir(path)`, `cache_dir(...)`, `stage_dir(data_dir, stage, fp)` | as research D-011 |
| `profiles.load` | `load_draft(path) -> dict`; `load_frozen(ref, profiles_dir) -> Profile` | |
| `profiles.weights` | `compute(draft: dict, purposes: dict) -> tuple[dict[str, float], str]` | weights, method |
| `profiles.validate` | `validate(draft: dict, config) -> list[str]` | list of error messages (empty = valid) |
| `scoring.rules` | `score(c: Criterion, x: float, sigma_e: float \| None = None, pct: Percentile \| None = None) -> CriterionScore`; `score_array(c, x: np.ndarray, pct=None) -> tuple[np.ndarray, np.ndarray]` | scores, deviations |
| `scoring.aggregate` | `aggregate(scores: Mapping[str, CriterionScore], profile: Profile) -> Aggregate`; `aggregate_arrays(scores: Mapping[str, np.ndarray], profile) -> tuple[np.ndarray, np.ndarray]` | overall, confidence |
| `scoring.percentile` | `Percentile.build(values, weights) -> Percentile`; `.lookup(x)`; `.to_json()/.from_json()`; `population_mask(name, ...) -> np.ndarray` | |
| `footprint` | `focal(values: np.ndarray, land: LandIndex, radius_km: float, statistic: Statistic, min_valid_fraction: float) -> np.ndarray` | land-aligned |
| `sources.base` | `Source.probe() -> ProbeResult`; `Source.fetch(request: dict) -> FetchResult`; `SourceRegistry.get(source_id) -> Source` | |
| `grid.build` | `build_grid(ctx) -> GridVersion`; builder classes `Builder.build(entry: dict, ctx) -> list[dict]` (manifest layer entries) | |
| `screening` | `run(ctx) -> ScreeningResult` | |
| `grouping` | `group(screening: ScreeningResult, ctx) -> list[CandidateArea]` | sets `upper_bound` |
| `refine.terrain` | `refine(area: CandidateArea, ctx) -> GroupResult` | |
| `refine.mineralogy` | `emit_coverage(footprint, ctx) -> bool`; `refine(area, ctx) -> GroupResult` | |
| `refine.scheduler` | `schedule(areas: list[CandidateArea], ctx) -> tuple[list[CandidateArea], dict]` | areas, `refinement` summary |
| `rank` | `rank(areas, screening, ctx) -> dict` | dict valid against `results.schema.json` |
| `calibrate` | `calibrate(results: dict, screening, ctx) -> dict` | `calibration.json` content |
| `dedup` | `dedup(results: dict, ctx) -> dict` | results with labels |
| `site.build` | `build_site(run_dir: Path, ctx) -> Path` | site directory |
| `pipeline` | `run_stage(name, ctx) -> Path`; `run_all(profile_ref, options) -> str` | stage dir; run_id |

Each stage function is pure with respect to its inputs: given the same `StageContext` inputs it
writes the same files (needed for stage fingerprints, research D-011).
