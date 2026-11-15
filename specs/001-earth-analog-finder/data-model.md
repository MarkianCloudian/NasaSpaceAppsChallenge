# Data Model: Earth Analog Finder

All persistent objects are JSON files (configuration, frozen profiles, results, manifests) or
GeoTIFF layers. JSON Schemas for each are in `contracts/`. Field names below are the JSON keys.

## Overview

```text
Purpose 1──* ReferenceProfile 1──* Criterion *──2 DataSource (planetary, earth)
ReferenceProfile ──freeze──> FrozenProfile (id@version, content_hash, computed weights)
LayerDefinition (config/layers.json) 1──* GridLayer ;  GridLayer ──from── DataSource
GridVersion 1──* GridLayer ;  GridLayer *── CachedDownload
Run ──uses── FrozenProfile + GridVersion ; Run 1──* EarthCandidate 1──* CriterionResult
Run 1──1 RunRecord ; Run 1──1 CalibrationReport ; EarthCandidate *──0..1 KnownAnalogSite (dedup)
```

## Purpose (`config/purposes.json`)

| Field | Type | Rules |
|---|---|---|
| `purpose_id` | string slug | unique; e.g. `rover_expedition`, `landing`, `permanent_base`, `astrobiology` |
| `description` | string | plain language |
| `category_ranks` | object category → integer rank | all 8 categories present; rank 1 = most important; ties allowed (equal ints) |
| `weight_method` | `roc` \| `direct` | default `roc` |
| `category_weights` | object category → number | only when method = `direct`; sum 1 |

Categories (fixed enum): `geology`, `terrain`, `thermal`, `resources`, `atmosphere`, `biology`,
`subsurface`, `operations` (the 8 challenge analogy categories).

## Reference Profile (draft: `profiles/<id>.json`; frozen: `profiles/frozen/<id>@<version>.json`)

| Field | Type | Rules |
|---|---|---|
| `profile_id` | string slug | unique |
| `version` | semver string | new version required for any change after first run (FR-009) |
| `body` | `Mars` \| `Moon` | |
| `purpose` | purpose_id | must exist in purposes.json |
| `reference_site` | {name, lat, lon, radius_km, crs, citation} | radius_km > 0 |
| `search_constraints` | {lat_range [min,max], max_landcover_fraction {class: 0..1}, min_barren_fraction?} | applied before scoring |
| `min_confidence` | 0..1 | default 0.6 |
| `percentile_population` | `eligible` \| `all_land` \| `ice_free_land` | default `eligible` (cells passing `search_constraints`, before vetoes); used by normalized criteria (D-021) |
| `category_overrides` | {category: {rank or weight, reason}} | reason mandatory (FR-006) |
| `criteria` | Criterion[] | ≥ 1 scored criterion |
| `removed_criteria` | [{id, reason}] | FR-005 record |
| `notes` | string | free text |
| *(frozen only)* `weights` | {criterion_id: number} | computed; sum 1 over scored |
| *(frozen only)* `weights_method` | string | e.g. `roc×roc`, `direct` |
| *(frozen only)* `content_hash` | sha256 hex | over canonical JSON of the draft |
| *(frozen only)* `frozen_at` | ISO date | |

## Criterion (inside a profile)

| Field | Type | Rules |
|---|---|---|
| `id` | slug | unique in profile |
| `category` | category enum | |
| `quantity` | slug | must match an Earth layer/refinement quantity name (e.g. `precip_annual`, `ndvi_max`, `slope_p90`) |
| `statistic` | string | e.g. `annual_total`, `annual_max_of_monthly_mean`, `p90_over_footprint` |
| `unit` | string | SI or declared (`degC`, `deg`, `m`, `mm/yr`, `fraction`, `index`, `class`, `bool`) |
| `baseline_m` | number | required when quantity is scale-dependent (slope, roughness) |
| `footprint_statistic` | `mean` \| `median` \| `max` \| `min` \| `p90` \| `p10` \| `fraction_true` | statistic over the circular footprint of `reference_site.radius_km` (D-017); same on both bodies; required unless `not_comparable` |
| `evaluation_scale` | `grid` \| `refinement` \| `both` | refinement value overrides grid value when both |
| `target` | {min?, max?} \| {classes[]} \| {value: bool} \| {percentile} | shape must match `scoring_rule` |
| `tolerance` | {low?, high?} \| {percentile} | > 0 where used |
| `veto` | number 0..1 \| null | score below → reject |
| `rank_in_category` | integer | used by ROC; ties allowed |
| `weight` | number | only when method `direct` |
| `comparison` | `absolute` \| `normalized` \| `not_comparable` | `not_comparable` → excluded from score |
| `scoring_rule` | `trapezoid` \| `gaussian` \| `boolean` \| `class_overlap` \| `percentile` | `percentile` ⇔ `normalized` |
| `value_status` | `measured` \| `placeholder` | placeholder → visible label |
| `uncertainty` | {target_sigma?, earth_sigma?} | optional; widens tolerance |
| `valid_bands` | string | required for spectral/mineral criteria (which parameters valid on both bodies) |
| `class_map` | ref to mineral_classes.json | for `class_overlap` |
| `sources` | {target: [{source_id or citation, version, accessed}], earth: [source_id]} | earth source ids must exist in sources.json unless `not_comparable` |
| `justification` | string | one line for target/tolerance/veto choice |

### Validation rules (B1)

1. Schema-valid (`contracts/profile.schema.json`).
2. Purpose exists; every category used is in the enum.
3. Weights: after freeze, scored weights sum to 1 ± 1e-6; `direct` weights given for all scored criteria.
4. Override of a category without `reason` → error.
5. `comparison = absolute` with a known Earth-impossible quantity (list in settings, e.g.
   `pressure`, `gravity`, `lunar_surface_temp`) → error.
6. Scale-dependent quantity (`slope*`, `*roughness*`, `relief`) without `baseline_m` → error;
   for `evaluation_scale` `grid`/`both`, `baseline_m` must equal the matching `config/layers.json`
   output `baseline_m` (±1 %); for refinement, the refinement method baseline (D-020).
7. `class_overlap` without `class_map` or `valid_bands` → error.
8. Earth `sources` reference unknown source id → error; criterion with `evaluation_scale = grid`
   whose quantity is not an output of any entry in `config/layers.json` → error.
9. `target`/`tolerance` shape inconsistent with `scoring_rule` → error.
10. Frozen id@version exists with a different content hash → error (FR-009).

### State transitions

`draft` → (validate ok) → `valid` → (freeze) → `frozen id@version` → (used by run) → `used`.
Any edit of a `used` version requires a new `version` → new frozen file.

## Mars v1 profile criteria (B3 starting point; numbers are placeholders until B3 sources them)

Purpose `rover_expedition` category ranks (proposal): operations 1, terrain 2, geology 3,
atmosphere 4, thermal 5, resources 6, biology 7, subsurface 8 (subsurface has no criterion in v1
→ dropped and remaining category weights renormalised).

All values are taken over the 20 km-radius footprint (research D-017); "fp stat" is the
criterion's `footprint_statistic`.

| id | category | quantity / statistic | fp stat | scale | rule / mode | target | tolerance | veto | rank |
|---|---|---|---|---|---|---|---|---|---|
| `hyperarid` | atmosphere | `precip_annual` / annual total | mean | grid | percentile / normalized | p\* = 0.0 (driest) | 0.05 | 0.2 | 1 |
| `dry_air` | atmosphere | `rh2m_mean` / annual mean | mean | grid | percentile / normalized | p\* = 0.0 | 0.10 | — | 2 |
| `no_vegetation` | biology | `ndvi_max` / annual max of monthly | p90 | grid | trapezoid / absolute | max 0.10 | high 0.05 | 0.5 | 1 |
| `barren_ground` | geology | `lc_frac_barren` / fraction of cell | mean | grid | trapezoid / absolute | min 0.7 | low 0.2 | 0.25 | 2 |
| `thermal_swing` | thermal | `lst_amp` / mean day−night of monthly | mean | grid | percentile / normalized | p\* = 1.0 (largest) | 0.15 | — | 1 |
| `regional_slope` | terrain | `slope_p90_1km` @ 926 m / p90 | p90 | grid | trapezoid / absolute | 0–5 deg | high 5 | — | 2 |
| `traverse_slope` | operations | `slope_p90` @ 30 m / p90 over footprint | p90 | refinement | trapezoid / absolute | 0–15 deg | high 10 | 0.3 | 1 |
| `roughness` | terrain | `rms_roughness` @ 30 m / median | median | refinement | trapezoid / absolute | 0.5–5 m | low 0.5, high 3 | — | 1 |
| `mineral_classes` | geology | `mineral_class_fractions` | mean | refinement | class_overlap / absolute | {Fe/Mg-smectite, carbonate, olivine} | — | — | 1 |
| `aqueous_minerals` | resources | `aqueous_mineral_present` | fraction_true | refinement | boolean / absolute | true | — | — | 1 |
| `pressure` | atmosphere | `surface_pressure` | — | — | not_comparable | ~0.6 kPa | — | — | — |
| `gravity` | operations | `gravity` | — | — | not_comparable | 3.71 m/s² | — | — | — |
| `thermal_inertia` | thermal | `thermal_inertia` | — | — | not_comparable | per THEMIS | — | — | — |

Removed (FR-005): `wind` (low relevance; model-only on Mars), `landform` (no automatic Earth
classification), `subsurface_feature` (no global Earth dataset).

## Data Source (`config/sources.json`)

| Field | Type | Rules |
|---|---|---|
| `source_id` | slug | unique |
| `provider`, `dataset`, `dataset_version` | strings | version mandatory |
| `body` | `Earth` \| `Mars` \| `Moon` | |
| `route` | `stac` \| `earthdata` \| `http` \| `rest` \| `manual` | `manual` only for hand-entered profile values (FR-016b) |
| `endpoint` | URL | documented provider URL |
| `collection` | string | STAC collection / CMR short name |
| `login` | `none` \| `earthdata` \| `api_key` | |
| `request_unit` | `tile` \| `bbox` \| `point` \| `granule` \| `file` | |
| `format` | string | e.g. `HDF4`, `COG`, `GeoTIFF`, `NetCDF4`, `JSON` |
| `rate_limit` | {requests, per_seconds} | conservative default if unknown |
| `retries` | integer | default 3 |
| `fallback` | source_id \| null | used on failure after retries, empty search result, or coverage < `coverage.min_coverage_fraction` (D-022) |
| `resolution` | string | |
| `coverage` | string | e.g. `52N–52S` |
| `licence`, `citation`, `docs_url` | strings | mandatory |

## Layer Definition (`config/layers.json`, `contracts/layers.schema.json`, research D-019)

| Field | Type | Rules |
|---|---|---|
| `layer_id` | slug | unique; groups one source read |
| `builder` | `modis_cmg` \| `landcover_fractions` \| `climatology_rest` \| `dem_block_stats` \| `gridded_netcdf` | must be a supported builder type |
| `fallback` | {builder, source_id, params} \| absent | alternative build with the same outputs (e.g. POWER → ERA5), D-019 |
| `source_id` | slug | must exist in sources.json, route not `manual` |
| `params` | object | builder-specific: variable names, scale, offset, nodata, quality rule, temporal statistic, reference years, block size |
| `resampling` | `none` \| `bilinear` \| `area_mean` \| `block_stats` \| `majority` | `bilinear` only for continuous quantities |
| `outputs` | [{layer_id, quantity, unit, statistic, baseline_m?}] | output layer ids unique across the registry; `baseline_m` required for slope/roughness/relief |

## Grid Version and Grid Layer

**GridVersion** (`data/grids/<grid_id>/manifest.json`, `contracts/grid-manifest.schema.json`):
`grid_id`, `cell` {size_deg 0.05, width 7200, height 3600, crs EPSG:4326, origin}, `land_mask`
layer id, `layers` [GridLayer], `built_at`, `build_seconds`, `status` (`complete` | `partial`),
`missing_layers` [{layer_id, reason}].

**GridLayer**: `layer_id`, `quantity`, `unit`, `statistic`, `source_id`, `dataset_version`,
`reference_period`, `resampling` (`none` | `bilinear` | `area_mean` | `block_stats`),
`baseline_m` (terrain), `file` (relative path), `fingerprint`, `nodata`.

State: `building` (`.partial-*` dir) → `complete` (`_COMPLETE`) ; never modified afterwards.

## Cached Download

Path `data/cache/<source_id>/<dataset_version>/<request_key>/`; `request_key` = fingerprint of the
request parameters (bbox/tile/granule id/time). Contains raw files + `request.json` +
`_COMPLETE`. Immutable.

## Run, Earth Candidate, Criterion Result (`results.json`, `contracts/results.schema.json`)

**RunRecord**: `run_id`, `profile` {id, version, content_hash}, `grid_id`, `settings` (copy),
`percentile_population` {name, cells}, `refinement` {stop (`bound_reached` | `cap_reached`),
proven_top, terrain_areas, mineral_areas, emit_covered_areas} (D-024), `stage_fingerprints` {stage: fp} (research D-011),
`sources` [{source_id, dataset_version, accessed}], `started_at`, `finished_at`, `stages`
[{name, status, seconds, fingerprint}], `counts` {evaluated_cells, rejected_by_constraint, rejected_by_criterion
{id: n}, areas, refined, insufficient_data, ranked}, `placeholder_values` bool, `dedup_applied` bool.

**EarthCandidate** (area): `area_id`, `rank` (null if not ranked), `status` (`ranked` |
`insufficient_data` | `rejected` | `screened_only`), `centroid` {lat, lon}, `representative`
{lat, lon}, `n_cells`, `area_km2`, `bbox`, `overall_score`, `confidence`, `limiting_criterion`,
`rejected_by` (criterion id | null), `footprint` {lat, lon, radius_km} (the evaluated circle,
D-017), `upper_bound` (0..1, D-024), `refinement_level` (`none` | `terrain` | `full`), `analogy_limits` [string], `label` (`known_analog` |
`new_candidate` | null), `known_site` (name | null), `results` [CriterionResult].

**CriterionResult**: `criterion_id`, `state` (`known` | `unknown` | `not_comparable`),
`relative` bool, `earth_value`, `unit`, `target` (copy), `deviation`, `deviation_ratio`, `score`,
`weight_effective`, `scale_used` (`grid` | `refinement`), `source_id`, `note`.

Ranking: by `overall_score` desc, then `confidence` desc, then `area_id` (deterministic).

## Known Analog Site (`config/known_analogs.json`)

`site_id`, `name`, `lat`, `lon`, `radius_km` (default 50), `bodies` [Mars|Moon], `purposes`
[purpose_id] (empty = all), `analog_for` (short text), `reference` (citation/URL).

## Calibration Report (`calibration.json`)

`known_sites` [{site_id, in_scope bool, out_of_scope_reason, footprint {lat, lon, radius_km}
(centred on the site, D-022), rejected_by, area_id (containing area, if any), rank,
percentile_rank, overall_score, limiting_criterion}] — `rank` and `percentile_rank` are
conservative (counting areas whose final score or upper bound exceeds the site's score, D-025), `flag_for_review` bool, `flag_reasons` [`no_known_analog_in_scope` |
`no_known_analog_in_top_20pct`] (D-018), `stability` {draws, range, seed, top_k,
candidates [{area_id, share_in_top_k}]}.

## Settings (`config/settings.json`)

`grid` {cell_size_deg, lat_range, reference_years}, `screen_min_score`, `max_area_km2`,
`refine` {batch 10, max_terrain_areas 200, max_mineral_areas 60, bound_margin 0.05,
terrain_hint true} (D-024), `site_top_n`, `stability` {draws, range, seed, top_k}, `known_radius_default_km`,
`cleanup_keep` {grids, runs}, `paths` {data, public}, `earth_impossible_quantities` [..],
`footprint` {min_valid_fraction 0.5, benchmark_budget_s 180}, `coverage` {min_coverage_fraction
0.5}, `emit` {min_band_depth 0.02, min_cluster_pixels 4, max_granules_per_area 5}, `http`
{timeout_s 60} (values to confirm in the verification task).
