# Implementation Plan: Earth Analog Finder

**Branch**: `001-earth-analog-finder` | **Date**: 2026-11-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-earth-analog-finder/spec.md`

**Note**: This plan is written so that individual sub-phases (section *Delivery Phases*) can be
picked up by different people. Each sub-phase states its goal, inputs, outputs, dependencies and
"done when" check. `/speckit-tasks` turns these sub-phases into numbered tasks; the plan itself
does not change scope relative to the spec.

## Summary

Find places on Earth that resemble a chosen Mars location for a chosen purpose (v1: one Mars
rover-expedition profile, Jezero crater delta). A frozen reference profile (JSON) lists criteria
with targets, tolerances, vetoes and weights. A Python command-line pipeline:

1. checks that every needed data source is reachable;
2. builds (or reuses) a global 0.05° Earth grid stacked from several datasets (MODIS land-surface
   temperature, vegetation and land cover on NASA's native 0.05° climate-modelling grid, ETOPO
   terrain, NASA POWER climate);
3. screens the whole grid with hard constraints and vetoes, groups surviving cells into candidate
   areas;
4. refines the best areas with detailed data (30 m terrain, EMIT mineralogy);
5. scores each criterion 0–1 against the profile, applies vetoes, combines with a weighted
   geometric mean, computes confidence and the limiting criterion;
6. calibrates against known analogs and checks weight stability;
7. (later stage) labels candidates that coincide with known analogs;
8. writes a static, script-light HTML site (inline SVG world map, one page per candidate) for
   GitHub Pages or Cloudflare Pages.

All stores (download cache, grid versions, runs) are versioned and never overwritten.

## Technical Context

**Language/Version**: Python 3.11+ (project venv via `uv`; system Python 3.7 is not used).

**Primary Dependencies**: numpy, scipy (connected-component grouping), rasterio (GeoTIFF/COG
read/write, windowed reads, ENVI for CRISM), pyhdf (MODIS HDF4 climate-modelling-grid files), h5py
(EMIT NetCDF4 groups, ERA5 fallback NetCDF), cdsapi (ERA5 fallback download), pystac-client +
planetary-computer (STAC search and signed COG access), earthaccess (NASA Earthdata search and
download), requests (REST/HTTPS), jsonschema (config and output validation), jinja2 (static
HTML). Standard library for CLI (`argparse`), hashing and JSON; all configuration is JSON.
See research D-005.

**Storage**: Files only. Download cache, grid versions, stage cache (`data/stages/<stage>/<fp>/`,
one entry per stage fingerprint) and runs under `data/` (git-ignored), layout and identity rules
in research D-002 and D-011. `public/` (published site, < 2 MB) is committed. Grid layers are compressed GeoTIFF;
results are JSON plus CSV; the site is static HTML/CSS/SVG.

**Testing**: pytest. Unit tests with hand-computed values for scoring, weights, fingerprints;
integration tests on a tiny synthetic grid fixture (no network); contract tests validating
configs and outputs against `contracts/*.schema.json`; site tests for size and absence of
external requests. Network-touching tests are marked `online` and skipped by default.

**Target Platform**: Team laptops (Linux/macOS/Windows) for the pipeline; any static host and
any modern browser (including scripting disabled) for the site.

**Project Type**: CLI data pipeline + static site generator (single project).

**Performance Goals**: grid build from cached inputs ≤ 10 min (SC-001); cached full run ≤ 10 min,
first run incl. downloads ≤ 60 min (SC-002); site initial download < 2 MB, opens < 3 s (SC-008).

**Constraints**: peak pipeline RAM ≤ 2 GB (windowed/row-band processing); disk for cache + grids
< 10 GB (SC-003); free data access only; no credentials in the repo; no external fonts or large
JS libraries on the site; deterministic output (fixed seeds, stable sorting).

**Scale/Scope**: global grid 7200 × 3600 cells at 0.05° (~7–8 M land cells); 1 reference profile
(v1) with ~10–12 criteria; top 30 candidate areas refined (configurable); ~10 known analog sites.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the plan complies | Status |
|---|---|---|
| I. Frozen Reference Profiles | `freeze` command computes weights (ROC) and writes `profiles/frozen/<id>@<version>.json` with a content hash; `run` refuses an id+version whose hash differs (FR-009). Profiles validated by `contracts/profile.schema.json` plus semantic checks. Purpose category ranks in `config/purposes.json`. | Pass |
| II. Measurement-Consistent Comparison | Each criterion declares quantity, statistic, unit, baseline, evaluation scale and footprint statistic; every Earth value is computed over the same circular footprint (profile reference radius) as the Mars target, at screening and final scoring (D-017); candidate areas only group cells for presentation. Mineral comparison via explicit crosswalk `config/mineral_classes.json`; atmospheric-band exclusions declared. Terrain computed at source resolution before aggregation (D-001, D-009). | Pass |
| III. Transparent, Non-Compensatory Scoring | Scoring rules + veto + weighted geometric mean in `scoring/` (D-012), all per-criterion results exported and shown on the site; no ML. Cross-profile comparison not offered. | Pass |
| IV. Provenance and Uncertainty | Every layer/result records source id, version, resolution; `value_status`; UNKNOWN state; confidence; run record + grid manifest (data-model). | Pass |
| V. Explicit Analogy Limits | `not_comparable` / `normalized` modes; analogy-limits text generated per candidate; "relative" labels on site. | Pass |
| VI. Validation Against Known Analogs | `calibrate` stage: known-analog ranks + weight-stability (D-014); `publish` refuses flagged runs unless `--allow-unvalidated`, which adds a "not validated" banner (D-018). | Pass |
| VII. Hackathon-Scale Simplicity | Pipeline order exactly: coarse grid → screening → refinement of top areas → scoring. Few dependencies, stdlib argparse, no database, no server. | Pass |
| Data & Technology Constraints | Python 3.11, constitution stack minus Streamlit/Folium/Plotly (replaced by static site, see Complexity Tracking); NASA sources: MODIS, EMIT, POWER, NASADEM; credentials via `~/.netrc` / env; `data/` git-ignored; no WMTS tiles as numbers. | Pass (justified deviation) |
| Development Workflow & Quality Gates | Unit tests for scoring/veto/UNKNOWN/renormalisation; schema validation tests; scripted, re-runnable stages; run record + manifests make rankings reproducible. | Pass |

**Post-design re-check (after Phase 1)**: re-evaluated against `data-model.md`, `contracts/` and
`quickstart.md` — no new violations. The only deviation remains the UI stack (below).

## Project Structure

### Documentation (this feature)

```text
specs/001-earth-analog-finder/
├── plan.md              # This file
├── research.md          # Decisions D-001…D-016 (clarify + Phase 0)
├── data-model.md        # Entities, fields, validation, state transitions
├── quickstart.md        # Setup + end-to-end validation scenarios
├── contracts/           # CLI contract, JSON Schemas, site contract
│   ├── cli.md
│   ├── internal-api.md      # shared types + module signatures (anti-drift)
│   ├── site.md
│   ├── profile.schema.json
│   ├── purposes.schema.json
│   ├── sources.schema.json
│   ├── settings.schema.json
│   ├── known-analogs.schema.json
│   ├── layers.schema.json
│   ├── grid-manifest.schema.json
│   └── results.schema.json
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root = `App/`)

```text
run.py                         # Main entry: thin wrapper → analogfinder.cli (runs all stages)
.github/workflows/pages.yml    # Deploys committed public/ to GitHub Pages (D-022)
pyproject.toml                 # Package + deps; console script `analog`
config/
├── settings.json              # Grid cell size, extents, top-N, seeds, cleanup keep-N, paths
├── sources.json               # Data-source entries (D-004 contract)
├── layers.json                # Grid layer registry: builder type, source, params, outputs (D-019)
├── purposes.json              # Purposes + category rank order (weights computed)
├── known_analogs.json         # Known terrestrial analog sites
└── mineral_classes.json       # Mineral hierarchy + CRISM↔EMIT crosswalk
profiles/
├── mars-rover-jezero.json     # Editable draft profile
└── frozen/                    # Frozen, versioned profiles (committed)
src/analogfinder/
├── types.py                   # shared types, exactly as contracts/internal-api.md
├── cli.py                     # argparse sub-commands (contracts/cli.md)
├── config.py                  # Load + schema-validate all config
├── storage.py                 # Fingerprints, atomic dirs, cache keys, cleanup
├── profiles/                  # validate.py, weights.py (ROC), freeze.py
├── sources/                   # base.py, check.py, stac.py, earthdata.py, http.py, power.py
├── grid/                      # cells.py (0.05° grid), build.py, builders/*.py (one per builder
│                              # type: modis_cmg, landcover_fractions, climatology_rest,
│                              # dem_block_stats, gridded_netcdf; D-019)
├── footprint.py               # Circular focal statistics over the profile radius (D-017)
├── scoring/                   # rules.py, aggregate.py, percentile.py
├── screening.py               # Hard constraints + grid-scale vetoes over whole grid
├── grouping.py                # Connected components → candidate areas
├── refine/                    # terrain.py (30 m DEM), mineralogy.py (EMIT)
├── planetary/                 # Optional target extraction: crism.py, dem.py (FR-010)
├── rank.py                    # Final scoring, ranking, run record
├── calibrate.py               # Known-analog ranks + weight stability
├── dedup.py                   # Later stage: known/new labels
└── site/                      # build.py, templates/*.html.j2, static/style.css, static/map.js,
                               # basemap/ (simplified Natural Earth coastline, public domain)
schemas/                       # Copies of contracts/*.schema.json used at runtime
tests/
├── unit/                      # scoring, weights, fingerprints, validation
├── integration/               # synthetic-grid end-to-end (offline)
├── contract/                  # config + output schema validation
├── site/                      # size budget, no external URLs, no-JS readability
└── fixtures/                  # tiny grids, sample profile, fake source responses
data/                          # git-ignored: cache/, grids/, runs/
public/                        # published site copy (output of `analog publish`)
```

Existing files stay where they are: `sample*.json` (historical drafts; `sample-edited.json` is
the seed for `profiles/mars-rover-jezero.json`), `solution_ideas.md`, `outputs/` (reports).
`spec-kit/` (cloned tool repo) is git-ignored.

**Structure Decision**: single Python project with a `src/` package, a thin `run.py` main script
that dispatches to stage sub-commands (user asked for a main script that runs the others), JSON
configuration outside code, and a generated static site. No backend/frontend split: the site has
no server.

## Delivery Phases (hand-off guide)

How to read: each sub-phase is a unit one person can take. **Depends on** lists sub-phases that
must be finished first; sub-phases without mutual dependencies can run in parallel (marked ∥).
**Done when** is the acceptance check. Spec references point to requirements the sub-phase
satisfies. User-story mapping: US1 = A–E + I, US2 = F, US3 = B, US4 = G, US5 = H.

### Phase A — Foundations (blocks everything)

**A1. Repository and environment**
- Goal: a runnable, reproducible project skeleton.
- Work: `git init`; `.gitignore` (`data/`, `public/` build temp, `.venv/`, `spec-kit/`, `.netrc`,
  `*.partial*`); `pyproject.toml` with deps from Technical Context and console script `analog`;
  `run.py` wrapper; empty package layout above; `uv` venv on Python 3.11; pytest configured with
  `online` marker skipped by default.
- Output: `analog --help` and `python run.py --help` print the sub-command list.
- Done when: fresh clone → `uv sync` → `uv run pytest` passes (zero tests is fine) on two team
  machines.
- Depends on: —. Spec: FR-015, constitution Data & Technology Constraints.

**A2. Configuration files and schemas**
- Goal: every tunable lives in JSON, validated before use.
- Work: copy `contracts/*.schema.json` into `schemas/`; write `config/settings.json`,
  `config/sources.json` (all entries from research D-004/D-007/D-008 inventory),
  `config/layers.json` (grid layer registry, D-019, schema `contracts/layers.schema.json`),
  `config/purposes.json` (rover_expedition with category ranks), `config/known_analogs.json`
  (seed list, data-model §Known Analog Site), `config/mineral_classes.json` (crosswalk, D-010);
  `config.py` loads each file and validates it, failing with file + JSON path of each error.
- Output: `analog validate --config` reports OK or a list of errors.
- Done when: contract tests validate every shipped config file; a broken copy fails with a
  readable message.
- Depends on: A1. Spec: FR-001, FR-016.

**A3. Storage layer** ∥ A2
- Goal: versioned, never-overwritten stores (D-002, D-011).
- Work: `storage.py` — canonical-JSON fingerprint (sha256, first 16 hex); atomic directory
  writes (`<name>.partial-<random>` → rename on success; `_COMPLETE` marker with manifest);
  download-cache key `source_id/version/request_key`; lookup "exists and complete"; `clean`
  that keeps last N grids/runs and every cache entry referenced by kept items.
- Output: library functions + `analog clean --dry-run`.
- Done when: unit tests prove (a) identical inputs → same fingerprint, key order irrelevant;
  (b) a killed write leaves no complete-looking directory; (c) cleanup never deletes referenced
  items.
- Depends on: A1. Spec: FR-013, FR-014, FR-014a–c.

**A4. Source access and pre-run check** ∥ A3
- Goal: one uniform way to fetch from STAC, Earthdata, HTTPS and POWER, plus a pre-flight check.
- Work: `sources/base.py` (interface: `probe()`, `fetch(request) → cached path`, rate-limit
  token bucket from `rate_limit`, bounded retries with backoff, fallback mirror); adapters
  `stac.py` (pystac-client + planetary-computer signing), `earthdata.py` (earthaccess, login via
  `~/.netrc` or env `EARTHDATA_USERNAME/PASSWORD`), `http.py` (plain documented downloads),
  `power.py` (POWER REST); `sources/check.py` runs `probe()` for every source a profile + grid
  needs and prints a table (source, route, login present?, reachable?, affected criteria).
- Output: `analog check --profile <id>`.
- Done when: with no Earthdata login configured, check reports EMIT/MODIS as "login missing"
  and names affected criteria, exit code 3 (contracts/cli.md); with login, all pass. Offline
  tests use fake adapters.
- Depends on: A2, A3. Spec: FR-016, FR-016a–c.

### Phase B — Reference profile (US3)

**B1. Profile validation**
- Goal: reject any profile that breaks the rules before analysis.
- Work: `profiles/validate.py` = schema validation + semantic rules from data-model §Validation
  (weights sum, override reasons, comparison mode vs. reproducibility, baseline for scale-
  dependent quantities, valid bands for spectral criteria, data sources exist in
  `sources.json`, evaluation scale consistent with available layers).
- Output: `analog validate --profile <file>` lists every error with field path.
- Done when: the spec's US3 scenarios 1–4 pass as tests using broken fixture profiles.
- Depends on: A2. Spec: FR-002–FR-008.

**B2. Weight computation and freezing** ∥ B1 (shares fixtures)
- Goal: ranks → numeric weights → frozen profile (D-003).
- Work: `profiles/weights.py` (ROC with ties; two-level multiply; drop empty categories and
  renormalise; `direct` passthrough; rounding to 6 decimals with residue to largest);
  `profiles/freeze.py` writes `profiles/frozen/<id>@<version>.json` incl. computed weights,
  `weights_method`, `content_hash`; refuses if that id@version exists with a different hash.
- Output: `analog freeze --profile profiles/mars-rover-jezero.json`.
- Done when: unit test reproduces the n=8 ROC values in research D-003; US3 scenario 1a and 5
  pass; freezing twice with no changes is a no-op.
- Depends on: B1. Spec: FR-006, FR-007, FR-009.

**B3. Mars v1 profile content**
- Goal: one complete, scientifically defensible Mars profile (FR-011).
- Work: start from `sample-edited.json` Mars profile; restructure to `contracts/profile.schema.json`;
  set the v1 criterion set from data-model §Mars v1 criteria (grid-scale + refinement split);
  fill targets from literature / planetary data with citation per value (`value_status:
  measured` where sourced); set tolerances and vetoes with a one-line justification each;
  rank criteria within categories; record removed criteria with reasons (FR-005).
- Output: `profiles/mars-rover-jezero.json` (draft) → frozen `@1.0.0`.
- Done when: B1 validation passes; every scored criterion has a source citation or is explicitly
  `placeholder`; reviewer (second team member) signs off on targets/tolerances.
- Depends on: B1, B2 (to freeze); can start in parallel as content work. Spec: FR-003–FR-005,
  FR-011.

**B4. Optional target extraction from planetary data** ∥ B3
- Goal: derive some B3 targets from data instead of by hand (FR-010, SHOULD), at the same
  baselines as the Earth side (D-020): 30 m for refinement criteria, 926 m for `regional_slope`
  (MOLA+HRSC 200 m DEM resampled).
- Work: `planetary/dem.py` — slope p90 / roughness at declared baseline from a Jezero CTX or
  HiRISE DTM (USGS STAC) over the reference footprint; `planetary/crism.py` — mineral class
  area fractions from CRISM MTRDR `_SU`/`_SR` files (ODE REST) using crosswalk thresholds.
- Output: `analog extract --profile <file>` prints proposed target values with sources.
- Done when: values printed for Jezero match published magnitudes within reason (reviewer check);
  output can be pasted into B3. If time is short, skip: B3 uses literature values.
- Depends on: A4, A2. Spec: FR-010.

### Phase C — Global Earth grid (US1)

All layers share the cell definition from C1 and are written as one GeoTIFF each into a grid
version directory (D-001, D-006). Layers are declared in `config/layers.json`; code implements
**builder types**, not products (D-019): C1 = `landcover_fractions`, C2 + C3 = `modis_cmg`
(same builder, two registry entries), C4 = `climatology_rest`, C5 = `dem_block_stats`.
Swapping a source of a supported format is a registry edit. C2–C5 are independent once C1
exists (C3 only adds registry entries and checks for the C2 builder).

**C1. Cell definition and land mask**
- Goal: one shared 0.05° global grid (7200 × 3600, lat 90…−90, lon −180…180, EPSG:4326) and an
  eligible-land mask.
- Work: `grid/cells.py` (transform, cell area per row, lat/lon of centres); land/water and land-
  cover class fractions from MODIS MCD12C1 (same native grid, no resampling); mask = land minus
  permanent water; exclusions (urban, cropland, snow/ice) stay as fraction layers so each profile
  can choose.
- Output: layers `land_mask`, `lc_frac_<class>` (barren, urban, cropland, snow_ice, water,
  forest, grass/shrub).
- Done when: land cell count is within 1% of expected (~29% of cells); a plotted mask matches
  coastlines.
- Depends on: A3, A4. Spec: FR-012.

**C2. Land-surface temperature layer** ∥ C3–C6
- Work: MODIS MOD11C3 v061 monthly 0.05° (12 months of a configured reference year range);
  read day/night LST with pyhdf, apply scale 0.02 and QC; compute per cell: annual max of monthly
  day LST, annual min of monthly night LST, mean, mean day−night amplitude (°C).
- Output: layers `lst_day_max`, `lst_night_min`, `lst_mean`, `lst_amp`.
- Done when: spot checks (Atacama, Sahara, Antarctica coast) have plausible values; documented
  caveat: monthly means smooth extremes — profile statistic names say "of monthly means".
- Depends on: C1. Spec: FR-012, FR-017.

**C3. Vegetation layer** ∥
- Work: MODIS MOD13C2 v061 monthly 0.05° NDVI; annual max NDVI per cell.
- Output: `ndvi_max`. Done when: deserts < 0.1, rainforest > 0.8. Depends on: C1.

**C4. Climate layers (NASA POWER)** ∥
- Work: POWER climatology (D-008) for T2M, RH2M, WS10M, PRECTOTCORR, ALLSKY_SFC_SW_DWN at native
  0.5° × 0.625°, requested in documented regional tiles, cached; bilinear resample to 0.05°
  (continuous fields). Fallback: registry `fallback` entry using builder `gridded_netcdf` with
  ERA5 monthly means from the Copernicus CDS API (one global request; D-008). No point requests.
- Output: `t2m_mean`, `t2m_min`, `t2m_max`, `rh2m_mean`, `ws10m_mean`, `precip_annual`,
  `insolation_mean`.
- Done when: all land cells filled; requests respect rate limit; re-run makes zero requests.
- Depends on: C1, A4. Spec: FR-012, FR-016c.

**C5. Regional terrain layers (ETOPO 2022)** ∥
- Work: ETOPO 2022 30″ surface elevation (D-009); process in row bands; compute slope (Horn) at
  30″ (~0.9 km) baseline and aggregate 6 × 6 blocks to 0.05°: slope p90, local relief (max−min),
  elevation std (roughness proxy), mean elevation.
- Output: `elev_mean`, `relief`, `slope_p90_1km`, `elev_std`.
- Done when: peak RAM < 2 GB; Himalaya high relief, Sahara low; documented baseline = ~1 km.
- Depends on: C1. Spec: FR-004, FR-012, FR-017.

**C6. Grid build orchestration and manifest**
- Work: `grid/build.py` — compute grid fingerprint (cell definition + each layer's source id,
  version, parameters, resampling); reuse if complete; otherwise build missing layers (per-layer
  fingerprints allow reuse of unchanged layers), write `manifest.json`
  (`contracts/grid-manifest.schema.json`), mark complete atomically; a failed layer is recorded as
  missing, others kept.
- Grid fingerprint = cell definition + layer registry entries (D-019). No percentiles in the
  grid (D-021).
- Output: `analog grid` → `data/grids/<grid_id>/`.
- Done when: second invocation finishes in seconds with "reused"; build from cache ≤ 10 min
  (time it, record in quickstart); disk ≤ SC-003 budget.
- Depends on: C1–C5 (can integrate layers incrementally). Spec: FR-012–FR-014, SC-001, SC-003.

### Phase D — Scoring engine (US1) ∥ Phase C

**D1. Criterion scoring rules**
- Work: `scoring/rules.py` — `trapezoid` (range + separate lower/upper tolerance, open bounds),
  `gaussian`, `boolean`, `class_overlap` (weighted Jaccard with hierarchy partial credit),
  `percentile` (normalized mode); uncertainty widens tolerance `τ_eff = sqrt(τ² + σ_t² + σ_e²)`;
  each returns score, deviation (unit), deviation/τ, state.
- Done when: unit tests with hand-computed values for every rule incl. edges (inside range,
  exactly at tolerance, open bounds, NaN → UNKNOWN). Spec: FR-019–FR-021.

**D2. Aggregation, veto, confidence**
- Work: `scoring/aggregate.py` — veto check first (reject + rejecting criterion); weighted
  geometric mean over KNOWN scored criteria with weights renormalised; confidence = Σ weights of
  KNOWN; limiting criterion; exclusion of `not_comparable`; vectorised version for whole-grid
  arrays.
- Done when: tests for veto short-circuit, UNKNOWN renormalisation, confidence, zero score →
  overall 0, deterministic tie-breaking. Spec: FR-022–FR-024, FR-026.

**D3. Earth percentile normalisation**
- Work: `scoring/percentile.py` — area-weighted ascending empirical CDF of a criterion's footprint
  values over the profile's `percentile_population` (D-021), computed per run in screening and
  stored in the run directory (never in the grid version); lookup for any value.
- Done when: the lowest value (e.g. driest) → p ≈ 0, the highest → p ≈ 1; population choice
  changes results as expected on a synthetic array with an "ice" region. Spec: FR-025.

### Phase E — Screening, grouping, refinement, ranking (US1)

**E1. Screening**
- Work: `footprint.py` — for each grid-scale criterion compute a focal statistic of its layer
  over a circle of the profile's `reference_site.radius_km` (area-weighted; kernel recomputed
  per 1° latitude band; land-only, processed in bands to stay < 2 GB) using the criterion's
  `footprint_statistic` (D-017); store in the run directory. `screening.py` — apply profile
  search constraints (lat range, land-cover exclusions as fraction thresholds) then grid-scale
  veto criteria on the **footprint values** (normalized criteria via per-run percentiles over the
  profile's `percentile_population`, D-021), ordered by measured selectivity, then compute the
  screening score over grid-scale criteria; record counts rejected per criterion.
- Output: screening score raster + rejection counts in the run directory.
- Done when: synthetic-grid integration test reproduces expected survivors; Mars profile run
  rejects > 95% of land (sanity, not a hard rule). Depends on: C6, D1–D3. Spec: FR-014, FR-018.

**E2. Grouping into candidate areas**
- Work: `grouping.py` — 8-connected components of surviving cells above a screening threshold,
  for presentation only; representative point = best cell (highest screening score); the
  area's evaluated footprint = circle of the profile radius around that cell; no averaging of
  values over the area (D-017); split components larger than `max_area_km2` on a fixed tile grid
  so separate maxima become separate candidates; compute each area's optimistic upper bound
  (D-024) for the refinement scheduler; no fixed top K.
- Done when: adjacent cells form one area; two separate blobs form two; deterministic IDs.
  Depends on: E1. Spec: FR-027.

**E3. Refinement — fine terrain** ∥ E4
- Scheduling (D-024): `refine/scheduler.py` runs a best-first queue over upper bounds; terrain
  (cheap) before EMIT (expensive); stops when the top N are proven or a cap is reached.
- Work: `refine/terrain.py` — for each area chosen by the scheduler, fetch NASADEM (or Copernicus GLO-30 fallback)
  COGs via STAC within the profile footprint radius around the representative point; compute
  slope p90 and RMS roughness at the profile's declared baseline (resampling DEM by area-
  averaging to that baseline first); cache per area.
- Done when: values reproducible across runs; only scheduler-selected areas fetched (log counts).
  Depends on: E2, A4. Spec: FR-004, FR-017, FR-018.

**E4. Refinement — mineralogy (EMIT)** ∥ E3
- Work: `refine/mineralogy.py` — search EMIT L2B MIN granules intersecting each area footprint
  (CMR via earthaccess), download (cached), orthorectify with GLT, map `group_1/2_mineral_id` to
  crosswalk classes (`config/mineral_classes.json`), compute class area fractions with minimum
  cluster size; areas outside 52°N–52°S or without granules → UNKNOWN.
- Done when: an Atacama test area yields expected classes (e.g. sulfates/clays present); no
  granule → UNKNOWN, not absent. Depends on: E2, A4. Spec: FR-017, FR-024.

**E5. Final scoring, ranking and run record**
- Work: `rank.py` — combine per area the grid-scale footprint values at the representative
  cell and the refined criterion results for the same footprint (refined value replaces grid
  value for the same criterion; record `footprint` {lat, lon, radius_km}); final veto + geometric mean + confidence; areas
  below minimum confidence → "insufficient data" list; rank; generate analogy-limits text from
  not-comparable/normalized/unknown criteria; write `results.json`
  (`contracts/results.schema.json`), `results.csv`, `run_record.json` into the run directory
  (run id = fingerprint of profile hash + grid id + settings).
- Done when: SC-004 and SC-005 checks pass (all fields present; two runs identical).
  Depends on: E3, E4 (works with either missing → UNKNOWN). Spec: FR-021–FR-030.

### Phase F — Static results site (US2) ∥ Phases C–E (develop against fixture results)

**F1. Page data export**
- Work: `site/build.py` reads `results.json` and produces per-profile compact data (top-N areas,
  rounded values) embedded in pages; no separate large JSON fetches.
- Done when: data for 30 candidates < 200 KB.

**F2. Basemap**
- Work: simplified Natural Earth 1:110m land polygons → one SVG path (equirectangular,
  simplified to ≤ 150 KB) committed under `site/basemap/`; candidate markers as SVG circles
  positioned from lat/lon at build time.
- Done when: map renders in browser with scripting off; file size within budget.

**F3. Templates**
- Work: Jinja2 templates: `index.html` (map + ranked table, profile selector as plain links),
  `candidate/<id>.html` (scores, per-criterion table with value/target/deviation/score/mode/
  source, analogy limits, known/new label, coordinates), `method.html` (plain-language scoring
  explanation, profile summary and weights), `about.html` (data sources + citations, run record
  summary). Labels for placeholder and relative values. System font stack, one CSS file.
- Done when: all pages readable with scripting disabled (site tests); every FR-036 field present.

**F4. Small optional script**
- Work: `static/map.js` (vanilla, < 10 KB): zoom/pan via SVG `viewBox`, hover tooltip, click →
  candidate page; table sort. Nothing essential depends on it.
- Done when: site works identically (minus interaction) without it.

**F5. Budget and safety tests, publish**
- Work: tests that total initial download < 2 MB, zero `http(s)://` references to fonts/scripts/
  styles outside the site, valid HTML; `analog publish --run <id>` copies the site to `public/`
  for GitHub Pages / Cloudflare Pages; `public/` is committed and `.github/workflows/pages.yml`
  deploys it (D-022). Publish gate (D-018): if `calibration.json` has
  `flag_for_review: true`, `publish` exits 8 unless `--allow-unvalidated`, which rebuilds the
  site with a "Not validated against known analogs" banner (with `flag_reasons`) on every page.
- Done when: SC-008, SC-009 checks pass; site served from `public/` with `python -m http.server`
  behaves as on a static host.
- Spec (F1–F5): FR-034–FR-039, SC-008–SC-010.

### Phase G — Calibration (US4)

**G1. Known analog list**
- Work: fill `config/known_analogs.json` (name, lat, lon, radius_km, bodies, purposes,
  reference) — seed: Lake Salda, Atacama (Yungay), Río Tinto, Haughton crater (Devon Island),
  McMurdo Dry Valleys, Pilbara, Mauna Kea/Hawaiʻi, Iceland highlands, Utah MDRS area.
- Done when: schema-valid; every entry has a literature reference.

**G2. Calibration report** ∥ G3
- Work: `calibrate.py` — for each relevant known site: evaluate a circle of the profile radius
  centred on the **site's own coordinates** (grid-scale circle values at the containing cell,
  hard constraints → `in_scope`, vetoes → `rejected_by` with score still reported, refinement for
  that circle), compute its full score, report rank (position among ranked areas), score,
  limiting criterion (D-022); set `flag_for_review` with `flag_reasons` if no relevant known site is in scope or
  none is in the top 20% (SC-006, D-018).
- Done when: report written to run dir and shown on site `about.html`.

**G3. Weight stability**
- Work: perturb category weights N times (default 500, fixed seed) by multiplicative noise
  (±range from settings) → renormalise → re-aggregate stored per-criterion scores → share of
  draws each top candidate stays in top group (D-014).
- Done when: deterministic for a given seed; results in calibration report.
- Depends (G1–G3): E5. Spec: FR-031, FR-032, SC-006.

### Phase H — Deduplication against known analogs (US5, later stage)

**H1. Dedup stage and site labels**
- Work: `dedup.py` — great-circle distance from each candidate area (nearest cell) to each known
  site; within radius → `known_analog` + site name, else `new_candidate`; site shows new
  candidates highlighted and known ones in a separate section; without the stage, site says
  "deduplication not applied".
- Done when: US5 scenarios 1–3 pass; SC-011 reported. Depends on: E5, G1, F3. Spec: FR-033.

### Phase I — Integration and hand-over

**I1. Main command and resume**
- Work: `analog run --profile <id>` executes check → grid → screen → refine → rank → calibrate →
  (dedup if enabled) → site; each stage is looked up in the stage cache by its fingerprint
  (D-011) and reused when complete; changing a config file re-runs only the stages that read it.
- Done when: killing the run mid-refinement and re-running resumes there (US1 scenario 6).

**I2. Quickstart validation and timings**
- Work: execute `quickstart.md` end to end on a clean machine; record actual timings and disk
  use against SC-001–SC-003; fix docs.
- Done when: every quickstart scenario passes and timings are written into `quickstart.md`.
- Depends on: all previous.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Constitution stack names Streamlit + Folium + Plotly; plan uses a generated static site (Jinja2 + inline SVG + optional tiny vanilla JS) instead | Spec FR-034/FR-038 and SC-008/SC-009 require static hosting (GitHub/Cloudflare Pages), no server, no heavy JS, readable without scripting, < 2 MB | Streamlit needs a running Python server (cannot be hosted on static pages); Folium/Leaflet and Plotly ship large JS bundles and need scripting to show anything |
| pyhdf dependency (HDF4) not in constitution stack | MODIS climate-modelling-grid products (MOD11C3, MOD13C2, MCD12C1) are distributed as HDF4; they match the 0.05° grid natively, avoiding global resampling and keeping the 10-minute target | Re-gridding 1 km tiled MODIS COGs from a STAC mirror globally would require hundreds of tiles per variable and break the time/disk budget |
