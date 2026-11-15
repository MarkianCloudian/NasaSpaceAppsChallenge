# Research & Decisions: Earth Analog Finder

Decision log for `spec.md`. Entries recorded during `/speckit-clarify` are marked
**Pre-plan**; `/speckit-plan` (Phase 0) extends this file with further research. Each entry uses
Decision / Rationale / Alternatives considered, plus **Revisit when** for decisions expected to
need review.

## Pre-plan decisions (from /speckit-clarify, 2026-11-15)

### D-001: Global Earth grid assembled from multiple datasets as aligned layers

- **Decision**: The grid is a stack of layers, one per grid-scale criterion quantity. Each layer
  comes from the dataset named in configuration and is resampled onto one shared cell definition
  (cell size, extent, land mask). Each layer records its source, version and resampling method.
- **Meaning of the question**: No single public dataset contains all grid-scale criteria
  (terrain, surface temperature, vegetation, land cover, climate). So the grid cannot come from one
  source; the real choice is *how* sources are combined: independent aligned layers (chosen), one
  hosted multi-dataset platform, or a mix.
- **Rationale**: Sources stay independent and replaceable by configuration (constitution I/VII;
  spec FR-001). A failing source makes only its own criteria unknown (FR-024, constitution IV).
  One shared cell definition makes every layer comparable cell by cell (constitution II).
- **Alternatives considered**:
  - *Single hosted platform* serving many layers: less assembly, but ties the project to one
    provider, usually needs an account/project, and makes provenance less visible.
  - *Mixed per layer*: most flexible, more configuration and testing; effectively a later
    extension of the chosen option.
- **Consequences / open points**:
  - Resampling method per layer must suit its quantity: area-weighted mean for continuous values
    (temperature, elevation statistics), majority/fraction for classes (land cover), and slope or
    roughness computed at source resolution *before* aggregation (not from an averaged DEM).
  - Layers have different native resolutions and dates; the grid inherits the coarsest and the
    per-layer date must be shown in the run record.
  - Land mask choice (which dataset defines "land") affects every layer; it is itself a layer.
- **Revisit when**:
  - a grid-scale source changes version, disappears or adds access restrictions;
  - cell size is changed (default about 5 km), especially toward 1 km, where build time and storage
    targets (SC-001, SC-003) may break;
  - a Moon/second Mars profile introduces grid-scale quantities no current layer covers;
  - a hosted platform becomes attractive for speed (would reopen the single-platform option).

### D-002: Versioned, non-overwriting storage for downloads, grid and runs

- **Decision**: Three separate stores, nothing overwritten:
  1. **Download cache**: raw files keyed by source, dataset version and area (e.g. bounding box or
     tile id); immutable once complete; never re-downloaded.
  2. **Grid versions**: one directory per grid version, identified by a fingerprint of the layer
     settings and cell definition; one file per layer plus a manifest (sources, versions, cell
     definition, resampling method per layer, build date).
  3. **Runs**: one directory per run (results, run record, calibration report, page), referencing
     the profile version and grid version used.
  Identical inputs → reuse (no new files). Changed inputs → new version beside the old. Cleanup
  keeps the last N and never deletes anything a kept run references.
- **Meaning of the question**: Repeated runs can either overwrite (simple, but history and
  reproducibility are lost and interrupted writes corrupt state), accumulate near-duplicates (disk
  fills, unclear which is current), or be *content-identified*: the same inputs always map to the
  same stored version, so repetition is free and changes are explicit.
- **Rationale**: Reproducibility of every ranking (FR-029, constitution IV and Development
  Workflow gate "reproducible from committed code, profile version and data manifest"). Old pages
  stay valid evidence. No conflicts because nothing is written twice to the same place.
- **Alternatives considered**:
  - *Single grid file overwritten each build*: simplest; loses history; partial writes break it.
  - *Layer files updated in place*: faster partial rebuilds; no history; grid and results can
    drift out of step.
- **Consequences / open points**:
  - Writes must be atomic (write to a temporary location, then mark complete), so an interrupted
    step is never mistaken for finished (FR-014b).
  - The fingerprint must include everything that changes values (source dataset version, cell size,
    extent, land mask, resampling method) and nothing incidental (timestamps, paths), or identical
    inputs will not be recognised.
  - Partial reuse: a grid version whose settings differ in only one layer could reuse unchanged
    layer files (by per-layer fingerprint) instead of rebuilding all; worth doing if rebuilds
    approach the 10-minute limit.
  - Concurrent runs by two team members on one machine are not expected; if needed, a simple lock
    per store is sufficient.
  - Large stores stay out of version control (constitution: Data and Technology Constraints);
    only small derived artefacts and the page may be committed or published.
- **Revisit when**:
  - storage exceeds the SC-003 limit (10 GB) or cleanup becomes frequent;
  - a data source publishes silent updates under the same version (fingerprints would then need
    file checksums, not only version ids);
  - the team needs to share grids between machines (would add a shared/remote store);
  - more than one profile runs regularly (per-layer reuse across grid versions becomes valuable).

### D-003: Weights entered as ranks, computed by the system (rank-order centroid)

- **Decision**: The team ranks the 8 analogy categories in the purpose configuration and the
  criteria within each category in the profile. The system computes weights with rank-order
  centroid (ROC) per level, multiplies the levels, and stores the final weights in the frozen
  profile. Direct numeric entry is allowed as method `direct`.
- **Formula (ROC)**: for n ranked items, the item at rank k gets
  `w_k = (1/n) · Σ_{j=k..n} 1/j`. Example n = 8: 0.340, 0.215, 0.152, 0.111, 0.079, 0.054,
  0.033, 0.016. Ties: tied items share the mean of the weights of the positions they occupy.
  Final criterion weight: `w_i = W_category(i) × w_i|category`; categories with no criteria in a
  profile are dropped and the remaining category weights renormalised to sum to 1.
- **Meaning of the question**: weights are never written into program logic (already fixed by
  FR-006 and constitution I). The open point was *who produces the numbers*: humans typing
  values (easy to get inconsistent), humans giving ranks with a formula producing values
  (chosen), or pairwise comparisons (rigorous, slow).
- **Rationale**: ranking is fast and robust for a small team; ROC is a published, reproducible
  rule (Barron & Barrett 1996); the result is still a plain number per criterion that can be
  inspected, sensitivity-tested (FR-032) and recalibrated as a new profile version.
- **Alternatives considered**: direct numbers only (kept as `direct` fallback); swing weighting;
  AHP pairwise comparison with consistency ratio (Saaty 1980), kept as a possible later method.
- **Future option — interactive weight sliders (user idea, 2026-11-15)**:
  - One slider per category (8 in total; the same mechanism can apply within a category). All
    weights stay in 0.00–1.00 and always sum to 1.00.
  - Moving one slider re-balances the other *unlocked* sliders proportionally to their current
    values. A slider can be locked (e.g. at 0.35); locked values do not move, and the remaining
    unlocked sliders share what is left (e.g. 0.65 among the other 7). Repeat: lock a second one,
    and the rest share the new remainder.
  - Re-balance rule: with `L` = sum of locked weights, slider `i` set to `v` (clamped to
    `0 ≤ v ≤ 1 − L`), each other unlocked slider `j` becomes
    `w_j' = w_j · (1 − L − v) / Σ_{unlocked k≠i} w_k`; if that sum is 0, the remainder is split
    equally. Values rounded to 0.01 with the rounding residue given to the largest unlocked slider,
    so the total stays exactly 1.00.
  - Two possible places, with different rules:
    1. **Profile authoring helper**: the slider result is exported as weights with method
       `direct` (or `slider`), validated and frozen as a new profile version. Fully compatible with
       constitution I.
    2. **Exploration on the results page**: the page re-scores candidates in the browser from the
       stored per-criterion scores (weighted geometric mean is cheap in small vanilla script). Vetoes
       and confidence do not change. Results MUST be labelled "custom weights — exploratory, not
       the frozen profile" and never replace the official ranking (constitution I, III). Requires
       candidate per-criterion scores in the page data and degrades to the official ranking when
       scripting is off (FR-038).
  - Not in the current scope; candidate for a later user story.
- **Revisit when**:
  - calibration (FR-031) shows known analogs ranking poorly and ranks alone are too coarse to fix it;
  - the weight-stability check (FR-032) shows rankings flip under small changes (consider AHP or
    sliders for finer control);
  - the slider feature is promoted to a user story (decide authoring vs. exploration, or both).

### D-004: Documented data-source entries plus a pre-run source check

- **Source roles in the check (analysis P3)**: per run, a source is `required` (primary source of
  a grid layer or criterion) or `fallback` (only referenced as a fallback). A failing `fallback`
  source is a warning, never a blocker; see `contracts/cli.md` *check*.
- **Decision**: Each data source is a configuration entry declaring provider, dataset id and
  version, access route (query API / catalogue search / direct file download), login need, request
  unit (tile, area, point), format, rate limit, licence and citation, and optional fallback mirror.
  Only provider-documented routes are allowed (documented scripted downloads included). A check
  stage probes every needed source before a run. Sources without a programmatic route feed only
  hand-entered profile values, with source, version and access date recorded.
- **Meaning of the question**: "retrieve via API" was not specific enough: sources differ in
  route (REST, catalogue search, plain file tree), login (none, free account, free key), request
  unit and limits, and a few needed sources have no API at all. Without a fixed contract the
  implementation could rely on undocumented or fragile routes, and failures would appear mid-run.
- **Rationale**: removes ambiguity at the configuration level; keeps sources swappable (FR-001);
  turns login and outage problems into an up-front report (FR-016a); keeps provenance complete
  (constitution IV); respects the free-access rule (constitution, Data and Technology Constraints).
- **Alternatives considered**: API-only (drops MOLA and simple mirrors); leaving details to the plan
  (keeps the ambiguity).

#### Source inventory (from `outputs/dataset_access_report.pdf`, live tests 2026-11-14)

| Use | Source | Documented route | Login | Notes |
|---|---|---|---|---|
| Grid: elevation → regional terrain | NASADEM (Planetary Computer `nasadem`); Copernicus GLO-30/90 (AWS open data, Earth Search STAC) | STAC search + COG download | none | SRTM via LP DAAC needs free Earthdata Login; OpenTopography needs free key |
| Grid: land-surface temperature | MODIS LST (Planetary Computer `modis-11A1-061`; LP DAAC; AppEEARS) | STAC / CMR + download | none (PC) / free Earthdata (NASA) | coarse climatology product to be chosen in plan |
| Grid: climate (air T, RH, wind, insolation) | NASA POWER | REST API (JSON/CSV) | none | point/regional requests; regional size limits to check in plan |
| Grid: climate alternative | ERA5 (Planetary Computer `era5-pds`; Copernicus CDS) | STAC / CDS API | none (PC) / free CDS key | |
| Grid: land cover / bare-land mask | ESA WorldCover (Planetary Computer) | STAC + COG | none | |
| Grid: vegetation (NDVI) | HLS L30/S30 (Planetary Computer `hls2-*`; LP DAAC) | STAC + COG | none (PC) / free Earthdata | too fine for global grid; refinement or coarse NDVI product instead |
| Refinement: mineralogy | EMIT L2B MIN / L2A RFL (LP DAAC, CMR/CMR-STAC, earthaccess) | CMR/STAC search + HTTPS | free Earthdata Login | 52°N–52°S only; the only NASA Earth mineral-ID source |
| Refinement: fine terrain | NASADEM / Copernicus GLO-30 | as above | none | |
| Profile (Mars): mineralogy | CRISM MTRDR (PDS ODE REST; PDS Geosciences HTTPS) | REST + HTTPS | none | use `_SU`/`_SR` summary files (≈82 MB), not full cubes |
| Profile (Mars): terrain | MOLA / MOLA+HRSC DEM (USGS Astrogeology); CTX / HiRISE DTMs (USGS STAC) | HTTPS download / STAC | none | |
| Profile (Mars): thermal inertia | THEMIS mosaics (USGS STAC) | STAC | none | |
| Profile (Mars): climate | Mars Climate Database | web interface only | free registration (full DB) | **no documented API → hand-entered values only (FR-016b)** |
| Profile (Mars): in-situ climate | Curiosity REMS / Perseverance MEDA (PDS Atmospheres) | HTTPS download | none | site-specific (Gale, Jezero) |
| Profile (Moon, later) | LRO Diviner, LOLA, M3, LROC (PDS / ODE / USGS STAC / Moon Trek) | REST / HTTPS / STAC | none | Diviner: gridded products, not raw RDR |

- **Known gaps / open points**:
  - Mars atmosphere: only MCD (no API) and rover in-situ data → Mars climate targets are
    hand-entered or extracted from REMS/MEDA files.
  - Quotas and rate limits were not stress-tested in the report; the plan must set conservative
    defaults and confirm them from provider documentation.
  - Planetary Computer anonymous tokens are rate-limited; a free subscription key raises limits.
  - The official challenge Resources tab still has to be checked for the "at least one NASA source"
    rule; EMIT, NASADEM/SRTM, HLS, MODIS and POWER are NASA-hosted candidates.
  - Earth geochemistry, permafrost, caves/lava tubes: no source in the report (criteria stay
    unknown or out of scope for v1).
- **Revisit when**:
  - a pre-run check repeatedly fails for a source (switch primary/fallback);
  - a provider changes its documented route, auth or rate limits;
  - a Moon profile is added (Diviner/LOLA entries become active);
  - a programmatic route for Mars climate becomes available.

## Phase 0 decisions (from /speckit-plan, 2026-11-15)

Items marked **verify** are facts taken from provider documentation or the dataset report that
must be confirmed by the person implementing the related sub-phase (plan section *Delivery
Phases*); a failed verification triggers the listed fallback, not a redesign.

### D-005: Language, environment and dependencies

- **Decision**: Python 3.11+ in a project venv managed by `uv` (system Python 3.7 is too old).
  Runtime deps: numpy, scipy, rasterio, pyhdf, h5py, pystac-client, planetary-computer,
  earthaccess, cdsapi, requests, jsonschema, jinja2. Dev: pytest. CLI via stdlib `argparse`.
- **File readers (analysis A3)**:

  | Format | Reader | Used for |
  |---|---|---|
  | MODIS HDF4 (MCD12C1, MOD11C3, MOD13C2) | pyhdf | grid builders `landcover_fractions`, `modis_cmg` |
  | GeoTIFF / COG (ETOPO, NASADEM, Copernicus, USGS Mars DTMs, MOLA+HRSC) | rasterio | `dem_block_stats`, refinement terrain, planetary DEM |
  | NetCDF4 / HDF5 with groups (EMIT L2B MIN; ERA5 fallback) | h5py | refinement mineralogy, `gridded_netcdf` builder |
  | ENVI `.IMG` + `.HDR` (CRISM MTRDR `_SU`/`_SR`) | rasterio (GDAL ENVI driver; band names from `.HDR`) | planetary CRISM extraction |
  | JSON (POWER, STAC, ODE, CMR) | stdlib json / requests | sources |
- **Rationale**: constitution stack; every dep has wheels on PyPI for Linux/macOS/Windows
  (**verify** pyhdf wheel for each team OS); argparse avoids an extra CLI framework.
- **Alternatives**: xarray/rioxarray (convenient, but adds weight; can be added later if a layer
  needs it); conda (heavier; only needed if pyhdf wheels fail → fallback).

### D-006: Grid definition = NASA MODIS Climate Modelling Grid (CMG), 0.05°

- **Decision**: 7200 × 3600 cells, 0.05°, EPSG:4326, cell edges at multiples of 0.05°, row 0 at
  90°N. Cell area varies with latitude and is used as weight in area statistics and percentiles.
- **Rationale**: MOD11C3, MOD13C2 and MCD12C1 are published natively on exactly this grid →
  no resampling for three layer families, minimal build time, ~5.5 km cells (fits spec
  assumption). Full float32 layer = 104 MB in RAM, ~10–40 MB compressed on disk.
- **Alternatives**: 1 km grid (breaks 10-minute/10 GB targets); H3 hexagons (extra dep, no native
  data on it).

### D-007: Grid layer sources

| Layer family | Source (NASA unless noted) | Native grid | Access | Login |
|---|---|---|---|---|
| Land mask, land-cover fractions | MODIS MCD12C1 v061 (yearly, `Land_Cover_Type_1_Percent`) | 0.05° CMG | earthaccess (CMR + HTTPS) | free Earthdata |
| Land-surface temperature | MODIS MOD11C3 v061 (monthly day/night LST, scale 0.02 K) | 0.05° CMG | earthaccess | free Earthdata |
| Vegetation | MODIS MOD13C2 v061 (monthly NDVI, scale 0.0001) | 0.05° CMG | earthaccess | free Earthdata |
| Climate | NASA POWER climatology (D-008) | 0.5° × 0.625° | REST | none |
| Regional terrain | ETOPO 2022 30″ surface elevation (NOAA NCEI; non-NASA) (D-009) | 30″ | HTTPS GeoTIFF | none |

- Reference period: configurable; default the latest 5 complete years for MODIS (monthly means
  averaged per calendar month first, then annual statistics).
- Download volume estimate (**verify**): MOD11C3 + MOD13C2 ≈ 120 files × 20–80 MB, MCD12C1 ≈ 1
  file, ETOPO 30″ ≈ 1–2 GB → total well under the 10 GB cache budget.
- **Fallbacks**: MODIS via AppEEARS area requests or Planetary Computer `modis-*-061` COGs (1 km,
  more work); ETOPO → Copernicus GLO-90 COG overviews from AWS.

### D-008: NASA POWER access for the grid

- **Decision**: use the POWER climatology API (documented REST, JSON) with regional requests
  tiled over land; cache each tile response; resample to 0.05° bilinearly (continuous fields only).
  Parameters: T2M, T2M_MIN, T2M_MAX, RH2M, WS10M, PRECTOTCORR, ALLSKY_SFC_SW_DWN.
- **Verified (T022, 2026-11-15, live API error messages of `/api/temporal/climatology/regional`)**:
  each side of the box must be 2°–10° ("at least a 2 degree range … otherwise use the point
  endpoint"; "maximum of 10 degree range"), and **only 1 parameter per request**. The response is
  a GeoJSON FeatureCollection, one Point feature per 0.5° × 0.625° cell, with
  `properties.parameter.<NAME>.{JAN…DEC,ANN}`. Consequence: one request per (tile, parameter) →
  7 parameters × ~250 land tiles ≈ 1 750 requests ≈ 1 h at 1 request / 2 s, once, then cached.
  No numeric rate limit is documented (HTTP 429 exists); keep the conservative 1 request / 2 s in
  `config/sources.json` `nasa-power` notes (T011).
- **Fallback (analysis A2)**: ERA5 monthly means on single levels via the Copernicus CDS API
  (`cdsapi`, free account + key in `~/.cdsapirc`, never in the repo): dataset
  `reanalysis-era5-single-levels-monthly-means`, variables 2 m temperature, 2 m dewpoint
  (→ relative humidity via the Magnus formula), total precipitation, 10 m u/v wind, surface solar
  radiation downwards, for the reference years; one global request at 0.25° (a few hundred MB),
  read with h5py by builder type `gridded_netcdf`, bilinear to 0.05°. Point requests are **not**
  used (≈ 60 000 points ≈ 33 h at the rate limit).
- **Rationale**: no login, NASA source, small volume (coarse native grid).

### D-009: Terrain at two scales

- **Decision**: grid scale — ETOPO 2022 30″ (~0.9 km) processed in row bands: slope (Horn) at
  native 30″, then 6 × 6 block aggregation to 0.05°: `slope_p90_1km`, `relief` (max − min),
  `elev_std`, `elev_mean`. Refinement scale — NASADEM (Planetary Computer `nasadem`) or Copernicus
  GLO-30 (`cop-dem-glo-30`) COGs for areas selected by the refinement scheduler (D-024): slope p90 and RMS roughness at the profile's
  baseline after area-average resampling to that baseline.
- **Rationale**: slope must be computed before aggregation (D-001 note); 1 km slope is only a
  regional proxy, so rover-scale terrain is refinement-only (spec edge case).
- **Planetary side**: Jezero CTX/HiRISE DTM via USGS STAC resampled to the same baseline (B4).

### D-010: Mineralogy comparison (refinement only)

- **Decision**: compare at **mineral class** level (D-010 crosswalk in `config/mineral_classes.json`):
  hierarchy group → subgroup → species with partial credit (1.0 / 0.7 / 0.4 / 0); class area
  fractions on both sides; score = weighted Jaccard with hierarchy credit. Mars side: CRISM MTRDR
  summary parameters thresholded (e.g. D2300 → Fe/Mg-smectite, BD2210_2 → Al-OH clay, MIN2295_2480
  → carbonate, SINDEX2 → sulfate, OLINDEX3 → olivine). Earth side: EMIT L2B MIN group_1/group_2
  mineral names mapped to the same classes.
- **Excluded**: BD1900/BD1400 hydration (Earth water-vapour bands), parameters above 2.5 µm (no
  EMIT coverage) — recorded in the criterion's `valid_bands` note.
- **Alternatives**: same-algorithm path (compute CRISM parameters on EMIT L2A reflectance) — more
  rigorous, more work; kept as a later improvement. Spectral angle — needs representative spectra.
- **Verify**: published CRISM parameter detection thresholds (Viviano-Beck et al. 2014) for the
  chosen classes; EMIT L2B v002 mineral index list.

### D-011: Storage layout and identities

```text
data/
├── cache/<source_id>/<dataset_version>/<request_key>/...   # immutable downloads
├── grids/<grid_id>/                                         # one grid version
│   ├── layers/<layer_id>.tif
│   ├── manifest.json
│   └── _COMPLETE
├── stages/<stage>/<stage_fp>/                              # shared stage cache (all stage work)
│   ├── …                                                    # e.g. screen: footprint/<criterion_id>.tif,
│   │                                                        #   percentiles/<criterion_id>.json,
│   │                                                        #   screening_score.tif, screening.json
│   └── _COMPLETE
└── runs/
    ├── index.json                                           # profile id@version → run ids by date
    └── <run_id>/                                            # one run: record + linked final files only
        ├── run_record.json                                  # incl. stage_fingerprints
        ├── results.json, results.csv, calibration.json, results.dedup.json   # hard links / copies
        └── site/                                            # hard links / copies
```

Rule (analysis P1): stage code writes **only** into the `data/stages/<stage>/<stage_fp>/` directory
that `pipeline.py` passes to it and never builds paths itself; run directories never hold stage
work.

- `grid_id` = first 16 hex of sha256 over canonical JSON of {cell definition, per-layer
  (source id, dataset version, parameters, reference period, resampling)}. `layer_id` fingerprint
  allows reuse of unchanged layers. `run_id` = fingerprint of {frozen profile content hash,
  grid_id, run settings}. Canonical JSON = sorted keys, no whitespace, floats as repr.
- Atomic writes: build into `<dir>.partial-<random>`, rename on success, then write `_COMPLETE`.
  Anything without `_COMPLETE` is ignored and may be deleted by `clean`.
- **Stage fingerprints (analysis A1)**: every stage output is stored once in a shared stage cache
  `data/stages/<stage>/<stage_fp>/` (with `_COMPLETE`), where `stage_fp` = fingerprint of the
  previous stage's fingerprint plus everything the stage reads:

  | Stage | Inputs in the fingerprint |
  |---|---|
  | `screen` | frozen profile `content_hash`, `grid_id`, settings `screen_min_score`, `max_area_km2`, `footprint.*` |
  | `refine` | screen fp; `dataset_version` and `fallback` of each used source; hash of `config/mineral_classes.json`; settings `emit.*`, `coverage.*`, `refine.*`, `site_top_n` |
  | `rank` | refine fp |
  | `calibrate` | rank fp; hash of `config/known_analogs.json`; settings `stability.*` |
  | `dedup` | rank fp; hash of `config/known_analogs.json`; `known_radius_default_km` |
  | `site` | rank, calibrate, dedup fps; frozen profile `content_hash`; `grid_id`; package version (templates); licence/citation fields of `config/sources.json` |

  `run_id` = fingerprint of the ordered stage fingerprints. A run directory holds
  `run_record.json` (with each stage's fingerprint) and materialises its final files
  (`results.json`, `results.csv`, `calibration.json`, `results.dedup.json`, `site/`) from the
  stage cache by hard link where possible, otherwise copy. Editing only `known_analogs.json`
  creates a new run that reuses `screen`, `refine`, `rank` and recomputes `calibrate`, `dedup`,
  `site`. `clean` keeps stage-cache entries referenced by kept runs.

### D-012: Scoring formulas (implementation reference)

- Range target, trapezoid (default): `s = 1` inside `[min, max]`; below: `max(0, 1 − (min − x)/τ_low)`;
  above: `max(0, 1 − (x − max)/τ_high)`; open bound = no penalty on that side.
- Gaussian (optional): `s = exp(−(d/τ)²)` with `d` = distance outside range.
- Uncertainty: `τ_eff = sqrt(τ² + σ_target² + σ_earth²)` (σ omitted when unknown).
- Deviation reported as `d` (unit) and `d/τ_eff`.
- Boolean: 1 match / 0 mismatch / UNKNOWN.
- Classes: weighted Jaccard `Σ min(a_k, b_k) / Σ max(a_k, b_k)` with hierarchy credit applied by
  matching each target class to its best-related Earth class.
- Normalized (percentile): `p = F_pop(x)` (area-weighted ascending CDF of footprint values over
  the profile's reference population, D-021; p = 0 lowest, p = 1 highest);
  `s = max(0, 1 − |p − p*| / τ_p)`; label "relative".
- Veto: if `s_i < veto_i` → reject; record criterion.
- Overall: `S = Π s_i^(w_i / Σ_known w)` over KNOWN scored criteria; confidence `C = Σ_known w_i`.
- Limiting criterion: lowest `s_i` (ties → higher weight first, then id).

### D-013: Screening order and candidate areas

- Hard constraints (lat range, land-cover fraction thresholds) → grid-scale vetoes sorted by
  measured selectivity (fraction of cells removed, computed on the fly) → screening score over
  grid-scale criteria → cells with screening score ≥ `screen_min_score` (settings) → 8-connected
  components (scipy.ndimage.label) → split components larger than `max_area_km2` → area stats
  (area-weighted) → refinement order and stopping by upper bound (D-024), no fixed top K.
- Area ids: `<profile_id>-<lat>_<lon>` of the representative cell (stable across runs).
- Superseded in part by D-017: screening and scoring use footprint (focal) values per cell; the
  area aggregation step only groups cells for presentation.

### D-014: Weight stability check

- Multiplicative noise on category weights: `w'_c = w_c · U(1 − r, 1 + r)`, renormalise, keep
  within-category split; default r = 0.25, N = 500 draws, fixed seed in settings. Report per top
  candidate the share of draws in which it stays in the top `k` (default 10).
- Rationale: simple, explainable form of SMAA (Lahdelma et al. 1998); reuses stored per-criterion
  scores, so it costs seconds.

### D-015: Static site technology

- **Decision**: Jinja2-generated HTML, one CSS file, system font stack, inline SVG world map from
  Natural Earth 1:110m land (public domain), simplified to ≤ 150 KB; one HTML page per candidate;
  profile choice via links; `<details>` for expandable sections; optional vanilla `map.js`
  (< 10 KB) for zoom/pan/tooltips/table sort. No external requests.
- **Rationale**: works with scripting off, tiny RAM footprint (no tile engine, no canvas), deploys
  as plain files to GitHub Pages or Cloudflare Pages.
- **Alternatives**: Leaflet + tiles (≥ 40 KB JS + tile requests, needs scripting); Folium
  (generates Leaflet pages); Streamlit (needs a server) — all conflict with FR-034/FR-038.

### D-016: Mars v1 criteria selection (summary; full table in data-model)

- Grid-scale (screening + scoring): hyperaridity (annual precipitation, normalized), vegetation
  absence (NDVI max, absolute, veto), barren ground fraction (absolute, veto), surface
  temperature range (normalized), near-surface humidity (normalized), regional slope at 1 km
  (absolute).
- Refinement: slope p90 and roughness at 30 m baseline (absolute, veto on slope), mineral classes
  (class overlap), aqueous-alteration minerals present (boolean).
- Not comparable (shown, not scored): atmospheric pressure, gravity, thermal inertia (no Earth
  product), radiation.
- Dropped with reason (FR-005): wind (low relevance to rover traverse, Mars values model-only);
  landform type (no automatic Earth classification in v1); subsurface features (no global Earth
  dataset).

## Analysis remediation decisions (from /speckit-analyze, 2026-11-15)

### D-017: Footprint-based evaluation (resolves analysis C1, constitution II)

- **Decision**: every Earth criterion value is computed over a circle of the profile's
  `reference_site.radius_km` around the evaluated location, with the criterion's
  `footprint_statistic` (`mean`, `median`, `max`, `min`, `p90`, `p10`, `fraction_true`). The Mars
  target uses the same radius around the reference site.
  - **Screening**: per run, for each grid-scale criterion, a focal (moving-window) statistic of
    its layer is computed over the circular footprint, so every cell carries "value of the 20 km
    circle centred here". Kernel: cells whose centres lie within the radius, area-weighted
    (cos latitude); the kernel is recomputed per latitude band of 1° because a fixed radius spans
    more 0.05° columns towards the poles. **Method (analysis N3): neighbour gathering on land
    cells only** — per 1° latitude band precompute the (row, column) offsets of the circular
    kernel (≈ 41 cells for 20 km); for chunks of ~1 M land cells gather neighbour values into an
    array of shape (chunk, k) and reduce along the last axis (`np.nanmean` with cos-latitude
    weights, `nanmax`, `nanmin`, `np.nanpercentile`, fraction of true); ≈ 160 MB per chunk.
    Cells with valid fraction below `footprint.min_valid_fraction` → NaN. One code path serves
    every statistic and the latitude-dependent kernel. An early benchmark on the real grid must
    show ≤ `footprint.benchmark_budget_s` (default 180 s) for all grid criteria of the Mars
    profile; record the measurement here. Results are stored in the stage cache
    (profile-dependent), never in the grid version (grid stays profile-independent).
  - **Grouping**: candidate areas are only clusters for presentation; each area is represented by
    its best cell, and its scores are the footprint values at that cell.
  - **Refinement**: fine terrain and EMIT use the same circle around the same best cell (already
    the case in plan E3/E4).
  - If the radius is below one cell (~5.5 km), the single containing cell is used and a note is
    added to the criterion result.
- **Rationale**: Principle II requires the same spatial support on both bodies; averaging over
  an area of arbitrary size (1 cell to 2500 km²) did not satisfy it.
- **Cost**: one focal pass per grid-scale criterion (≈ 6 for the Mars profile); expected tens of
  seconds to a few minutes on land-only data; to be measured in plan I2.
- **Measured (T047, 2026-11-15)** with `scripts/benchmark_footprint_real.py` on a real grid
  (land mask and land-cover fractions from MCD12C1 2023, grid `a13f9adacf6f8d47`; **8,506,369
  land cells**, more than half of them poleward of 52°); radius 20 km, `min_valid_fraction` 0.5;
  laptop, Python 3.14. Time depends on land cells and kernel size, not on values: layers not built
  for this measurement (`precip_annual`, `rh2m_mean`, `ndvi_max`, `lst_amp`, `slope_p90_1km`) were
  replaced by fixed-seed random fields; `lc_frac_barren` is the real layer.

  | Pass | Cells computed | Time | Peak RSS |
  |---|---|---|---|
  | `hyperarid` mean (alone) | 8.51 M | 88 s | 1.11 GB |
  | `dry_air` mean (alone) | 8.51 M | 85 s | 1.09 GB |
  | `no_vegetation` p90 (alone) | 8.51 M | 68 s | 1.01 GB |
  | `barren_ground` mean (alone) | 8.51 M | 71 s | 1.10 GB |
  | `thermal_swing` mean (alone) | 8.51 M | 73 s | 1.09 GB |
  | `regional_slope` p90 (alone) | 8.51 M | 69 s | 1.00 GB |
  | all six, one `focal_many` pass, all land | 8.51 M | **218 s** (over the 180 s budget) | 1.59 GB |
  | all six, one pass, Mars profile `lat_range` [−52, 52] (what screening runs) | 3.94 M | **24 s** | 1.57 GB |

  Before the optimisation the all-land single pass took 244 s (same machine). Changes made (T047):
  neighbour values gathered in float32 with float64 sums for means (equal inputs still give
  exactly equal outputs; float32 sums changed near-tie rankings), int32 neighbour indices, and a
  `targets` mask so only cells that can pass the profile's latitude constraint are computed when
  the percentile population is `eligible` (neighbours still come from all land, so their values
  are identical to a full pass — unit test). **Within budget for the Mars v1 profile** (24 s,
  1.57 GB). A profile without a latitude limit, or with population `all_land` / `ice_free_land`,
  needs the all-land pass (218 s, 1.6 GB): over the time budget, within RAM; the remaining cost is
  the polar rows (kernel width ∝ 1/cos lat). Options if that case matters: per-band kernels
  capped by a metric reprojection near the poles, or `np.partition`-based quantiles.
- **Revisit when**: profiles need footprints much larger than 50 km (kernel cost grows with
  area) or non-circular footprints.

### D-018: Publish gate on calibration (resolves analysis C2, constitution VI)

- **Decision**: `calibration.json` carries `flag_for_review` and `flag_reasons` (`no relevant
  known analog in scope`, `no relevant known analog in top 20%`). `analog publish` refuses a
  flagged run with exit code 8 unless `--allow-unvalidated` is passed; then every page shows a
  "Not validated against known analogs" banner with the reasons. `analog site` still builds
  locally so the team can inspect the flagged results.
- **Rationale**: Principle VI says results MUST NOT be presented before a flagged profile is
  revisited; a local review build is not a presentation, publishing is.
- **Revisit when**: calibration sets grow enough for a numeric acceptance threshold per profile.

### D-019: Layer registry in configuration (resolves analysis I2)

- **Decision**: `config/layers.json` (schema `contracts/layers.schema.json`) declares every grid
  layer: `layer_id`, `builder` (one of the supported builder types), `source_id`, `params`
  (product variable names, scale factor, nodata, quality rule, temporal aggregation, reference
  years), and `outputs` (output layer ids with quantity, unit, statistic, `baseline_m` where
  scale-dependent). Builder types in v1:
  - `modis_cmg` — any MODIS 0.05° CMG HDF4 product; params name the variables, scale, QC rule and
    temporal statistics (serves MOD11C3 LST and MOD13C2 NDVI from the same code);
  - `landcover_fractions` — MCD12C1 class-percent cube → class-fraction layers + land mask;
  - `climatology_rest` — NASA POWER climatology tiles → bilinear to 0.05°;
  - `dem_block_stats` — any global GeoTIFF DEM → slope (Horn) at native resolution + block
    statistics to 0.05°;
  - `gridded_netcdf` — any global regular lat/lon NetCDF4 grid (e.g. ERA5 monthly means) →
    temporal statistics → bilinear to 0.05° (analysis A2).
  A registry entry may carry a `fallback` {builder, source_id, params} producing the **same
  outputs**; it is used when the primary build fails or returns too little coverage (e.g.
  `power_climate` → ERA5 via `gridded_netcdf`).
  Swapping a source (e.g. another MODIS collection, Copernicus GLO-90 instead of ETOPO) is a
  configuration edit when the builder type fits; a new file format needs a new builder type
  (code), which FR-012 now states explicitly.
- **Consequences**: grid fingerprint = fingerprint of the layer registry entries + cell
  definition; profile validation (rule 8) checks criterion quantities against registry outputs;
  data-model and tasks name builders, not products.
- **Revisit when**: a needed source fits no builder type.

### D-020: Baseline of scale-dependent grid criteria (resolves analysis I1, option B)

- **Decision**: a scale-dependent criterion with `evaluation_scale` `grid` or `both` MUST state
  `baseline_m`, and validation checks it equals the `baseline_m` of the matching output in
  `config/layers.json` (tolerance ±1 %); refinement criteria are checked against the refinement
  method's baseline (30 m for `traverse_slope`, `roughness`). Mars v1: `regional_slope`
  `baseline_m: 926` (ETOPO 30″ north–south spacing).
- **Mars side**: `planetary/dem.py` gets a regional mode: MOLA+HRSC blended DEM (USGS
  Astrogeology, 200 m) resampled by area-averaging to 926 m, Horn slope, p90 over the 20 km
  footprint → `regional_slope` target.
- **Known limitation**: on a 30″ geographic grid the east–west spacing shrinks with latitude
  (≈ 463 m at 60°); slope is correct (Horn with true spacing), but the baseline is anisotropic.
  Added to the analogy-limits text for `regional_slope`; revisit (metric reprojection, option C)
  if high-latitude candidates matter.
- **Rationale**: stores the baseline once (in the registry) and catches profile/layer mismatches
  automatically; fixes the shipped profile failing validation rule 6.

### D-021: Percentile reference population (resolves analysis I3, option C)

- **Decision**: profile field `percentile_population` ∈ {`eligible` (default), `all_land`,
  `ice_free_land`}:
  - `eligible` — cells passing the profile's hard search constraints (lat range, land-cover limits,
    land mask), evaluated **before** vetoes so the population does not depend on scoring;
  - `all_land` — every `land_mask` cell;
  - `ice_free_land` — land cells with footprint-mean `lc_frac_snow_ice` < 0.5.
  For each normalized criterion the screening stage computes the area-weighted ascending CDF of
  its **footprint values** (D-017) over the chosen population, stores it in
  `data/stages/screen/<screen_fp>/percentiles/<criterion_id>.json`, and records the population and its cell count
  in the run record. The grid build computes no percentiles (stays profile-independent).
- **Why not grid-level percentiles**: values being ranked are footprint statistics that depend on
  the profile radius, and the population depends on the profile's constraints; both are per run.
- **Why `eligible` default**: ice sheets and other excluded land would otherwise occupy the
  extreme percentiles (e.g. driest, coldest) and push accepted Mars-analog sites toward the veto,
  although those areas can never be candidates.
- **Relation to deduplication (US5)**: deduplication does not address this. It runs after scoring
  and only labels candidates near listed known analogs; it never changes the population. Using the
  known-analog list to shape the population would make scores depend on a literature list rather
  than physical constraints and change all normalized scores whenever a site is added; known-site
  radii also cover < 0.1 % of land, so they would not remove the ice-sheet effect anyway.
- **Revisit when**: a profile needs a custom population (e.g. a named region) — add a
  `bbox`/region option rather than hard-coding.

### D-022: Remaining second-review fixes (N1, N2, U1, U5)

- **N1 — grid size**: fixed at 0.05° in v1 (FR-012 reworded); `cell_size_deg` stays `const 0.05`
  in the settings schema.
- **N2 — calibration footprint**: each relevant known site is evaluated on a 20 km circle
  centred on the **site's own coordinates**: grid-scale circle values at the containing cell,
  hard constraints (`in_scope`), vetoes (`rejected_by`, score still reported), refinement for
  that circle, full score; rank and top-20 % test are **conservative** (D-025).
- **U1 — fallback trigger**: a source's `fallback` is used when (a) the request fails after
  retries, (b) the search returns no items/granules for the area, or (c) the fetched data covers
  less than `coverage.min_coverage_fraction` of the circle; the criterion result's `source_id`
  records the source that actually served the data (e.g. Dry Valleys south of 56°S: NASADEM
  empty → Copernicus GLO-30). EMIT has no fallback → UNKNOWN.
- **U5 — deployment**: `public/` (< 2 MB, the reviewed site) is committed; workflow
  `.github/workflows/pages.yml` deploys it on push to `main` with `actions/upload-pages-artifact`
  (path `public`) and `actions/deploy-pages`; no pipeline runs in CI (data stays on laptops).
  Cloudflare Pages: no build command, output directory `public`. Alternative (not chosen):
  publish to `docs/` with branch deployment.

### D-023: Third-review fixes (P1, P2, P3, A4, U2)

- **P1 — single location for stage work**: see the D-011 layout and rule above.
- **P2 — run resolution for stage commands**: every stage command accepts `--run RUN_ID`,
  `--latest`, or `--profile ID@VER` (= latest complete run of that profile from
  `data/runs/index.json`). It takes the base run's stage fingerprints, computes or reuses its own
  stage, writes a new run record if the combination is new, updates the index and prints
  `run: <run_id>`. `site`, `publish`, `status` accept `--latest`.
- **P3 — check statuses**: `OK` (reachable, login present); `FAIL` (required source unreachable or
  login missing and no usable fallback → exit 3); `WARN` (fallback source unusable, or required
  source failing with an `OK` fallback → "will use fallback"; exit 0). At run time, primary and
  fallback both failing → affected criteria UNKNOWN, exit 6.
- **A4 — DEM grid registration**: the `dem_block_stats` builder detects registration from the
  GeoTIFF transform and size. Cell-registered (origin −180, 90; 43200 × 21600 at 30″): 6 × 6 blocks
  directly. Grid-registered (origin −180 − ½ px, 90 + ½ px; 43201 × 21601): drop the last column
  (+180 duplicates −180) and last row (−90), assign each node to the 0.05° cell
  `floor((lon + 180) / 0.05)`, `floor((90 − lat) / 0.05)` (edge nodes go east/south) → exactly
  36 nodes per cell, half-pixel offset recorded in the manifest. Slope is computed on the native
  array before assignment. Any other geometry → `ConfigError` listing what was found. Which case
  ETOPO 2022 uses is recorded in the verification results.
- **U2 — site inputs snapshot**: the `site` stage writes `site_inputs.json` into its stage cache:
  frozen profile (via `run_record.profile`, `content_hash` verified), used `sources.json` entries
  (licence, citation, version, docs URL), grid-manifest layer entries (source, reference period,
  resampling, `baseline_m`), calibration summary. Templates render only from this snapshot and
  the results files, never from live config, so rebuilding an old run shows what it used. Layer
  periods appear on the about page (covers analysis A7 display).

### D-024: Bound-driven, cheap-first refinement (resolves analysis P4, variant d+e+f)

- **Problem**: with the v1 weights, refinement-only criteria carry ≈ 0.68 of the weight
  (traverse_slope .346, roughness .164, mineral_classes .116, aqueous_minerals .055) and screening
  sees ≈ 0.32. A fixed "top K by screening score" can drop areas that would rank best after
  refinement (example: grid 0.7 + excellent terrain/minerals → final 0.86 beats grid 0.9 + poor
  terrain → 0.56). Weights stay a human decision; the pipeline must cope.
- **Criterion groups**: refinement criteria are grouped by the data that supplies them:
  `terrain` (traverse_slope, roughness; 30 m DEM, a few MB per area, cheap) and `mineral`
  (mineral_classes, aqueous_minerals; EMIT, ~118 MB per scene, expensive). Groups are derived
  from each criterion's earth source, not hard-coded.
- **Upper bound (d)**: for an area with grid-scale scores `s_i` (weights `w_i`) and optimistic
  estimates `u_j` for not-yet-measured criteria, for an availability scenario A (set of groups
  assumed to have data):
  `S_ub(A) = exp( Σ_{i∈G∪A} w_i·ln(x_i) / Σ_{i∈G∪A} w_i )`, with `x_i = s_i` (measured) or `u_j`
  (estimate). The area's bound is `max_A S_ub(A)` over scenarios whose confidence
  `C(A) = Σ_{i∈G∪A} w_i ≥ min_confidence` (scenarios below it can never be ranked). With two
  groups there are at most 4 scenarios. Because the final score uses the same weighted geometric
  mean over the criteria that turn out known, and every real score ≤ its estimate, the final
  score never exceeds the bound (scenarios cover every possible availability).
- **Tightening from cheap information (e)**:
  1. EMIT coverage: a CMR granule search (metadata only, seconds, no download) for the area's
     footprint; no granule → the `mineral` group is impossible and dropped from all scenarios.
  2. Terrain hint (setting `refine.terrain_hint`, default true): rover-scale slope p90 at 30 m is
     in practice not lower than regional slope p90 at 926 m, so `u_traverse_slope` = score of the
     regional slope value × (1 − `refine.bound_margin`) instead of 1. Statistical, not a strict
     law: the verification task measures on refined areas how often it is violated; if > 5 %,
     disable the hint.
  3. All other unmeasured criteria: `u = 1`.
- **Best-first schedule (d + f)**: one priority queue keyed by each area's current bound:
  unrefined → key = bound with all groups estimated; after terrain → key = bound with terrain
  measured; fully refined → key = exact final score. Repeat: take the top `refine.batch` entries;
  fully refined entries whose score ≥ the best remaining key are **confirmed** into the results;
  unrefined ones get the terrain pass; terrain-done ones get the EMIT pass (or become final when
  no EMIT coverage). Stop when `site_top_n` areas are confirmed (`refinement_stop:
  bound_reached`) or when `refine.max_terrain_areas` / `refine.max_mineral_areas` is reached
  (`cap_reached`, number of proven top areas recorded). Ties broken by `area_id` → deterministic.
- **Outputs**: every area keeps `upper_bound` and `refinement_level` (`none`, `terrain`, `full`);
  unrefined areas are `screened_only`; run record gets `refinement` {stop, proven_top,
  terrain_areas, mineral_areas, emit_covered_areas}; site shows "top N proven complete" or the cap
  warning.
- **Cost**: terrain carries ≈ 0.51 of the weight, so after the cheap terrain pass bounds become
  tight and EMIT downloads go only to areas that can still enter the top N. Defaults:
  `refine.batch` 10, `max_terrain_areas` 200, `max_mineral_areas` 60, `bound_margin` 0.05.
- **Alternatives rejected**: fixed larger top K (no guarantee); re-weighting to suit the pipeline
  (changes scientific priorities for a technical reason); documenting only (missed candidates
  stay invisible).
- **Revisit when**: a profile has more expensive groups (e.g. Moon: Diviner, M3); generalise
  groups and costs in configuration.

### D-025: Screening preview and conservative calibration rank (fourth review Q1, Q2)

- **Q1 — `--skip-refine` = screening preview**: with no refinement, refinement-only criteria are
  UNKNOWN and confidence (≈ 0.32 for the Mars v1 weights) is below `min_confidence`, so no area
  can be ranked. Defined behaviour: every area that passes screening is listed by screening score
  as `screened_only` with its `upper_bound`; `run_record.refinement.stop = "skipped"`;
  `calibrate` and `dedup` are skipped; the site shows a "Screening preview — not ranked" banner;
  `publish` refuses with exit 8 (no override; preview is never presented as results). Purpose:
  fast look at where screening points, and online smoke testing.
- **Q2 — conservative rank**: with bound-driven refinement only the top N are exactly scored.
  For a known site with score `S_site`: `rank_conservative = 1 + #{areas : final score >
  S_site, or (not fully refined and upper_bound > S_site)}`. Because every unrefined area's true
  score ≤ its bound, the true rank is never better than reported (never flatters calibration).
  `percentile_rank = rank_conservative / #areas that passed screening`; the site is "in the top
  20 %" if `percentile_rank ≤ 0.2` (SC-006). Same rule for `flag_reasons`
  `no_known_analog_in_top_20pct`.
  Implemented (T077) as `rank_conservative ≤ max(1, ⌊0.2 · #areas⌋)`: identical to
  `percentile_rank ≤ 0.2` for 5 or more areas; with fewer areas rank 1 still counts (otherwise a
  site no area can beat would be flagged, which contradicts the T080 scenario "rank 1, no flag").
  Only in-scope, not vetoed sites with confidence ≥ `min_confidence` count for the test.

### D-026: Collaboration safeguards for parallel and agent-driven work

- **Shared types and module signatures** are fixed in `contracts/internal-api.md` and implemented
  once in `src/analogfinder/types.py` (task T007, first Foundational task); every later code
  task depends on it. Changes to the contract go into that file in the same pull request.
- **Code conventions**: Python 3.11, full type hints, `ruff` lint + format (configured in
  `pyproject.toml`, T002/T005).
- **Working rules for people and agents** are in `CLAUDE.md` (*Working on a task*): read-first
  list, one task per PR into `dev-app-v1` (any branch name; small manual fixes may be pushed
  directly), the person starting a task checks its dependencies, never change contracts or
  invent data values silently, run tests and ruff, ask on the issue when ambiguous.
- **Status**: the GitHub issue (closed by "Closes #N" in the PR) is the task status; feature PRs
  do not tick `tasks.md`; one maintainer ticks it in batches to avoid merge conflicts.
- **`@claude` in issues**: the workflow on `main` checks out `dev-app-v1`, branches from it
  (`base_branch`), installs `uv` and may run `uv`, `git`, `ruff`, `pytest` (see
  `.github/workflows/claude.yml` on `main`).
- **`.specify/feature.json`** is committed so `/speckit-*` commands work right after cloning.

## Verification results

### ETOPO 2022 30″ surface elevation (T042, 2026-11-15)

- **File URL** (single global file, anonymous HTTPS, range requests supported):
  `https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/30s/30s_surface_elev_gtif/ETOPO_2022_v1_30s_N90W180_surface.tif`
  (found via the NCEI product page; recorded in `config/sources.json` `etopo-2022.endpoint`).
- **Size**: 1,585,813,987 bytes (1.48 GiB), within the D-007 download estimate.
- **Registration (D-023 A4)**: GeoTIFF header reads 43200 × 21600, float32, pixel 1/120°, tie point
  (−180, 90) → **cell-registered**; the grid-registered branch is only exercised by synthetic tests.
- **Full-globe run** of `dem_block_stats` on this file: 620 s on a CI runner, **peak RSS 894 MB**
  (< 2 GB). Himalaya box (26–36°N, 76–92°E) max block relief 3857 m (> 2000 m); Grand Erg
  Oriental sand sea (29–31°N, 7–9°E) max block relief 171 m, median 54 m (< 200 m).
- Still **verify**: licence, DOI and the fallback choice (`copdem-glo30-pc` vs. GLO-90).
- Note: no `http` source adapter exists yet; the builder calls `source.fetch({"url": endpoint,
  "file": "dem.tif"})` and expects a `.tif` in the returned directory.

### Mars DEM targets for Jezero (T072, 2026-11-15)

- **MOLA + HRSC blended DEM** (`mola-hrsc-blend`): direct file URL recorded as `endpoint` in
  `config/sources.json` (302 → USGS S3 bucket); 11,384,463,908 bytes; range requests supported
  (HTTP 206); GeoTIFF int16, geographic on the Mars 2000 sphere (R 3 396 190 m), pixel
  0.003374120830641° (~200 m), nodata −32768. `planetary/dem.py` reads only the footprint
  window, area-averaged to 926 m.
- **CTX DTMs** (`usgs-mars-dtm-stac`, collection `mro_ctx_controlled_usgs_dtms`): items carry a
  `dtm` asset (COG, float32, nodata −32767, ~20 m, Equirectangular clon = 0); several DTMs are
  mosaicked over the 20 km footprint and area-averaged to 30 m on a geographic grid.
- **Measured over the 20 km footprint around the Jezero delta (18.44° N, 77.45° E)**:
  `regional_slope` slope p90 = 6.21° @ 926 m (coverage 1.00); `traverse_slope` slope p90 =
  12.00° @ 30 m (8 CTX DTMs, coverage 1.00); `roughness` median RMS of detrended neighbour
  differences = 0.37 m @ 30 m (same DTMs). The circle includes part of the crater rim, which
  raises the 30 m slope p90. These are proposals for T036; the profile still holds placeholders
  until T036 adopts them and a second team member reviews them.
- Still **verify**: licence and citation of both products.

### CRISM summary parameter thresholds (T036, 2026-11-15)

Checked against the primary sources: Viviano-Beck et al. 2014, JGR Planets 119, 1403–1431,
doi:10.1002/2014JE004627 (published PDF from CaltechAUTHORS, record 53039) and the PDS
Geosciences Node *CRISM Summary Parameter Calculation Reference* (July 2026).

- **No per-parameter detection thresholds are published.** Section 5.3 of the paper defines only
  display stretches: for band-depth parameters the lower limit is fixed at 0 (band depth zero)
  and the upper limit is the larger of the 99th percentile of a cumulative histogram over more
  than 100 representative scenes and the 99.9th percentile of the scene's own histogram; the
  percentile values are not tabulated. The PDS reference gives formulas only.
- The paper also states (sec. 6) that the strength of a summary product cannot be used to infer
  mineral abundance and that positive identification needs spectral analysis. Class fractions
  from thresholded parameters (`planetary/crism.py`, T073) are therefore indicative only.
- **False-positive caveats** (paper Table 2) for the parameters used in `crism_rules`: D2300 —
  Mg-carbonate also strongly > 0; BD2210_2 — gypsum, alunite; MIN2295_2480 — hydroxylated
  silicate + zeolite mixtures (both carbonate overtones must be present); SINDEX2 — ices;
  OLINDEX3 — high-Ca pyroxene, Fe-phyllosilicates.
- **Consequence**: the thresholds 0.015 / 0.01 / 0.01 / 0.02 / 0.1 stay as a documented project
  choice (`"status": "project_choice"` with the note above in `config/mineral_classes.json`).
  With them the Jezero footprint gives carbonate in only 0.05 % of valid pixels (T074), below the
  0.1 % proposal cut, although Mg-carbonate in the Jezero delta is established in published
  CRISM analyses. Options for the team: (a) keep the published-literature class list as the
  `mineral_classes` target (T036) and treat the CRISM fractions as supporting evidence only;
  (b) replace the fixed thresholds by a scene-relative rule following the paper's stretch logic
  (e.g. above the scene's 99th percentile of positive values); (c) lower individual thresholds
  after inspecting spectra. Not decided here.
- Note: the OLINDEX3 formula printed in the paper's Table 2 (weights over 1080–1470 nm) differs
  from the PDS reference (1210–1330 nm); MTRDR `_SU` files carry the delivered values, so
  `planetary/crism.py` is not affected.

### Remaining Jezero targets (T036, 2026-11-15)

Closes the placeholders left after the CRISM/terrain/climate part of T036. Sources:

- **`gravity`** = 3.73 m/s² (was 3.71): NASA NSSDCA Mars Fact Sheet, last updated 19 May 2025,
  "Surface gravity (mean)" 3.73 (equator 3.69). 3.71 appears only in older versions of the sheet.
- **`thermal_inertia`** = 200–450 SI: Martínez et al. 2022, LPSC 53, abstract 2024 — THEMIS
  (100 m/px) along the Perseverance traverse 200–450; MEDA in situ 200 (sand) to 600 (bedrock).
  The orbital range matches the footprint scale better than the in-situ range (old placeholder).
- **`hyperarid`**: Mars side sourced (MCD v6.2 water column ≈ 12.6 pr-µm; Haberle et al. 2001,
  doi:10.1029/2000JE001360, surface liquid water at most transient); p* = 0 stays a design mapping.
- **`barren_ground`** (min 0.7; team decision, option B: veto 0.25 dropped and tolerance low
  widened 0.2 → 1.0, so non-barren footprints lose score instead of being excluded; a tolerance
  ≤ 0.7 would still give 0 at barren 0 and act as a veto through the geometric mean). IGBP class 16 *Barren* =
  ≥ 60 % non-vegetated area with < 10 % vegetation (Sulla-Menashe & Friedl, Collection 6 MODIS
  Land Cover user guide, Table 3). Real MCD12C1 2023, 20 km footprint mean: Atacama (Yungay) 1.00,
  Sahara (Tanezrouft) 1.00, Namib 1.00, Danakil 1.00, Death Valley 0.92, MDRS Utah 0.73;
  Lake Salda, Río Tinto, Pilbara 0.00 (shrubland/grassland), Mauna Kea 0.25.
- **`no_vegetation`** changed from max 0.10 / tolerance 0.05 to **max 0.15 / tolerance 0.10**.
  Real MOD13C2 2023 annual-max NDVI over land cells with barren fraction > 0.9 (|lat| ≤ 52°,
  n = 644 004): p50 0.106, p90 0.147, p95 0.166, p99 0.222. The old values vetoed NDVI > 0.125,
  i.e. about half of MODIS-barren land, including Death Valley (footprint p90 0.148) and MDRS
  (0.149). New veto point (score 0.5) is NDVI 0.20. Literature gives bare land NDVI ≈ 0.1–0.2 and
  no universal cutoff, hence the data-based value. Vegetated mineral analogs stay vetoed (Lake
  Salda 0.58, Río Tinto 0.67, Pilbara 0.30): the rover-expedition profile targets plant-free
  terrain; a mineral-analog purpose would need its own profile.
- Site coordinates used for these checks are approximate area centres; one reference year only
  (2023). Re-check once the full 2019–2023 grid exists.

### Outcomes for the remaining verify items (T086, 2026-11-15)

Recorded by the T086 task. Status **VERIFIED** = checked against a primary source (named);
**NOT VERIFIED** = needs credentials, downloads or a built grid that were not available when this
was written; nothing below is an invented value, and each open item names its fallback and the
task whose run must fill it in. Replace a **NOT VERIFIED** line with the measured outcome when the
run is done.

| Item (task) | Status | Outcome / fallback |
|---|---|---|
| POWER regional limits (T022) | VERIFIED | See D-008 *Verified (T022)*: box sides 2°–10°, 1 parameter per request, ≈ 1 750 requests, 1 request / 2 s kept. |
| ETOPO file URL/size (T042) | VERIFIED | See *ETOPO 2022 30″* above: URL, 1,585,813,987 bytes, cell-registered. Licence, DOI and the GLO-30/GLO-90 fallback choice stay open (see that subsection). |
| pyhdf wheels per OS (T002) | VERIFIED (PyPI JSON `https://pypi.org/pypi/pyhdf/json`, pyhdf 0.11.7) | CPython 3.11 wheels: Linux `manylinux_2_28_x86_64`, Windows `win_amd64`, macOS **arm64 only** (`macosx_26_0_arm64`). **No** Linux aarch64 and **no** macOS Intel wheel → those machines build from the sdist (needs HDF4 libraries) or use the fallback: conda for pyhdf (D-005). Not installed or tested on macOS/Windows by this task. |
| MODIS download volume (T038–T040) | NOT VERIFIED | Needs Earthdata login and a real download. D-007 estimate (≈ 120 files × 20–80 MB + 1 MCD12C1 + ETOPO ≈ 1.5 GB, under the 10 GB budget) stands as an estimate. Fallback if exceeded: reduce `grid.reference_years` or use AppEEARS / Planetary Computer COGs (D-007). |
| CRISM thresholds used (T013/T073) | CHECKED, NOT A PUBLISHED VALUE (T036, 2026-11-15) | Viviano-Beck et al. 2014 does not publish per-parameter detection thresholds (see *CRISM summary parameter thresholds (T036)* below). The five values in `config/mineral_classes.json` are a project choice, now marked `"status": "project_choice"`; results that use them stay provisional. |
| EMIT version used (T051) | NOT VERIFIED | `config/sources.json` `emit-l2b-min` targets L2B MIN **V002** (docs `https://lpdaac.usgs.gov/products/emitl2bminv002/`); the DOI is still marked "verify" and no CMR search was run (needs network access to Earthdata). Fallback if V002 mineral list differs: update `config/mineral_classes.json` version. |
| ERA5 CDS request size/time (T043) | NOT VERIFIED | Needs `~/.cdsapirc` (not available; credentials never go in the repo). D-008 estimate (one global 0.25° request, a few hundred MB) stands. Only relevant if the POWER route fails. |
| Footprint benchmark (T047) | MEASURED (2026-11-15) | Real land mask (8.51 M land cells): all six Mars-profile criteria in one pass 24 s / 1.57 GB with the profile's latitude range (within the 180 s / 2 GB budget); 218 s / 1.59 GB over all land (over the time budget). Details and method in D-017 *Measured (T047)*. |
| Terrain-hint validity (D-024) | NOT VERIFIED | Needs refined areas (first real run). Measure the share with 30 m slope p90 < 926 m slope p90; if > 5 %, set `refine.terrain_hint` to `false` in `config/settings.json`. Currently `true` (default, unmeasured). |
| Refinement counts and stop reason of first real run | NOT VERIFIED | No real run done yet. Record `run_record.refinement` {stop, proven_top, terrain_areas, mineral_areas, emit_covered_areas}. |
| Settings values (T010) | VERIFIED (read from `config/settings.json`) | `grid.cell_size_deg` 0.05; `lat_range` [-90, 90]; `reference_years` 2019–2023; `screen_min_score` 0.3; `max_area_km2` 2500; `refine` batch 10, max_terrain_areas 200, max_mineral_areas 60, bound_margin 0.05, terrain_hint true; `site_top_n` 30; `stability` draws 500, range 0.25, seed 42, top_k 10; `known_radius_default_km` 50; `cleanup_keep` grids 2, runs 5; `footprint` min_valid_fraction 0.5, benchmark_budget_s 180; `coverage.min_coverage_fraction` 0.5; `emit` min_band_depth 0.02, min_cluster_pixels 4, max_granules_per_area 5; `http.timeout_s` 60. |

### Performance pass (T087, 2026-11-15)

Tool: `scripts/benchmark_perf.py` (`footprint`, `grid`, `disk`). Machine: 2-core CI runner, 7 GB RAM.

**Measured** — footprint pass (T046), synthetic land mask (smoothed random blobs, 30 % land, seed 0),
band 30–40°N (436,355 land cells), values random float32, `min_valid_fraction` 0.5:

| radius | per statistic (s per 10⁶ land cells) | all 7 statistics in one `focal_many` | peak RSS |
|---|---|---|---|
| 20 km (Jezero profile) | 1.0–1.1 | 3.9 s per 10⁶ cells | 440 MB |
| 100 km | 20–28 (median/p90/p10 slowest: sort) | 90 s per 10⁶ cells | 562 MB |

**Extrapolation (estimate, not measured)** to the whole globe, assuming ≈ 29 % land cells
(≈ 7.5 M cells; the 29 % is an assumption, not a dataset value) and the 30–40°N cost per cell
(kernels are larger towards the poles, so the figure is optimistic at high latitude):
20 km ≈ 0.1 min per criterion (0.5 min for all seven statistics); 100 km ≈ 3 min per criterion
(≈ 11 min for all seven). Memory is bounded by `max_elements` (4 M gathered values per chunk),
independent of latitude.

**Not measured here** (need the downloaded sources, NASA Earthdata/Copernicus credentials and
~GBs of data, which the CI runner does not have): grid build from cached inputs (SC-001),
`data/` disk use (SC-003), cached and first full run (SC-002). Run
`uv run python scripts/benchmark_perf.py grid` / `disk` after `analog grid` on a machine with the
data and record the numbers here; T088 replaces the quickstart _TBD_ values from them. The only
earlier real-data figure is the ETOPO `dem_block_stats` full-globe run above (620 s, 894 MB peak).

**Optimisation**: none applied — no measured target was missed, and the slowest measured part
(100 km footprints at ≈ 11 min for seven statistics) is outside the 10-minute grid-build target
(the footprint pass is part of the run, not of the build). Open item: confirm after real-data timing.

### Known analog sites (T076, 2026-11-15)

`config/known_analogs.json`: the nine seed sites of T076, all `bodies: ["Mars"]`, `purposes: []`
(relevant to every Mars profile; whether a site is in scope for a profile is decided by
calibration, T077).

- **References**: each title, journal, volume, pages and DOI was checked against the Crossref
  metadata of the DOI. Two citations of an earlier draft were replaced because they were not
  about the site: Lake Salda (Horgan et al. 2020 is about Jezero itself) → Gunes et al. 2024,
  Geobiology 22, e12619; Haughton (the cited "Overview" title was not found on Crossref) → Osinski et al.
  2005, MAPS 40, 1859–1877 (impact hydrothermal activity at Haughton).
- **Coordinates**: Wikipedia/GeoHack coordinates of the named feature, rounded to 0.01°: Lake
  Salda, Haughton crater, McMurdo Dry Valleys, Mauna Kea, Mars Desert Research Station. Others
  are area centres, **verify**: Yungay (−24.08, −70.01; literature gives the University of
  Antofagasta station near the old Yungay mine at ≈ 24°S, 70°W without a clean figure),
  Río Tinto (Minas de Riotinto headwaters), Pilbara (North Pole Dome / Strelley Pool area),
  Iceland highlands (central highlands; the Ehlmann et al. 2012 samples come from several
  localities).
- **`radius_km`**: project choice per site (20–80 km, roughly the extent of the analog terrain);
  sites without a value use `known_radius_default_km` (50).
