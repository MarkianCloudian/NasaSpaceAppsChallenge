# TerraAnalog Explorer Constitution

## Core Principles

### I. Frozen Reference Profiles

- Every Mars/Moon reference ("etalon") profile MUST be fully defined before it is used to
  evaluate Earth data: body, purpose, reference site (lat, lon, footprint radius), criteria,
  targets, tolerances, vetoes, weights and data sources.
- A profile MUST be identified by `profile_id` and a version. Any change to targets, tolerances,
  vetoes or weights MUST produce a new version; results MUST record which version produced them.
- Earth results MUST NOT be used to adjust a profile's targets. Tolerances, vetoes and weights may
  be recalibrated only through Principle VI, and only as a new version.
- Criteria MUST be selected per purpose. A criterion is kept only if it is relevant to the purpose,
  measurable on both bodies (or explicitly marked `not_comparable`), and not redundant with
  another kept criterion. Removing a criterion requires a recorded justification.
- Weights MUST be defined per profile using a recorded method (`roc`, `swing` or `ahp`), derived
  from purpose-level category weights; any site-level override MUST carry an override reason.
- Profiles MUST validate against the project's JSON Schema before use.

Rationale: a reference that moves while the search runs makes every ranking circular and
irreproducible.

### II. Measurement-Consistent Comparison

- A planetary value and an Earth value MUST be compared only when they describe the same physical
  quantity, with the same statistic, the same units and the same spatial support (footprint size
  and resolution/baseline).
- Raw measurements MUST NOT be converted across incompatible measurement types (e.g. elemental
  oxide wt% versus spectral mineral detections) without an explicit, documented bridge method
  whose uncertainty is carried forward.
- Every criterion MUST be converted to a dimensionless similarity score in [0, 1] by a declared
  scoring function (e.g. trapezoid, gaussian, percentile, weighted Jaccard, Aitchison distance,
  Wasserstein distance). Aggregation operates only on these scores.
- Scale-dependent quantities (slope, roughness) MUST be computed at a declared common baseline;
  DEMs MUST be resampled with area-weighted aggregation, not nearest-neighbour.
- Spectral criteria MUST list the bands/parameters valid on both instruments and exclude bands
  masked by atmospheric absorption on either body.

Rationale: comparing numbers of different kinds produces plausible-looking but meaningless scores.

### III. Transparent, Non-Compensatory Scoring

- The overall score MUST be computed by a documented, deterministic formula. The default is: per
  criterion veto check, then a weighted geometric mean of the remaining criterion scores, with
  weights summing to 1.
- A criterion whose score falls below its veto threshold MUST reject the candidate regardless of
  other scores; evaluation of remaining criteria for that candidate MAY stop early.
- Every result MUST expose the per-criterion scores, the overall score, the confidence value and
  the limiting (lowest-scoring) criterion.
- Machine-learning models MAY assist exploration but MUST NOT be the sole basis of a ranking
  shown to users.
- Scores from different profiles MUST NOT be compared directly; comparisons across profiles use
  within-profile ranks or percentiles.

Rationale: users and judges must be able to see why a site ranks where it does, and one severe
mismatch must not be hidden by many good matches.

### IV. Provenance and Uncertainty

- Every value in a profile or result MUST record its source dataset (name, version/collection ID),
  spatial resolution, and status (`measured` or `placeholder`). Placeholder values MUST NOT appear
  in published results without a visible label.
- Measurement uncertainty from both sides SHOULD be propagated into criterion scores where it is
  known; where it is unknown, this MUST be stated.
- Missing or uncovered data MUST be recorded as `UNKNOWN`, never as absent or as a mismatch.
  "Absent" requires sufficient instrument coverage and sensitivity.
- Each result MUST report confidence `C = Σ w_i` over criteria with data. Candidates below the
  profile's minimum confidence MUST be flagged or excluded from ranking.

Rationale: planetary coverage is patchy (e.g. CRISM targeted footprints); treating gaps as
evidence would silently bias rankings.

### V. Explicit Analogy Limits

- Criteria that cannot be reproduced on Earth (e.g. vacuum, gravity, lunar thermal extremes) MUST
  be either marked `not_comparable` and excluded from the score, or scored with a declared
  `normalized` (Earth-percentile) mode and labelled as relative.
- Every presented candidate MUST include a statement of where the analogy breaks down.
- Absolute claims of similarity MUST NOT be made for criteria scored in `normalized` mode.

Rationale: no Earth site is a full analog; overstating similarity is a scientific error.

### VI. Validation Against Known Analogs

- Scoring thresholds, tolerances and veto levels MUST be checked against a recorded calibration
  set of recognised terrestrial analogs (e.g. Atacama, Río Tinto, Haughton crater, Antarctic Dry
  Valleys, Hawaiʻi lunar regolith sites) for the relevant profile.
- Each profile's weights MUST undergo a sensitivity check (random perturbation of weights) before
  results are published; ranking stability MUST be reported.
- If known analogs do not rank in the profile's upper results, the profile's tolerances or
  weights MUST be revisited (as a new version) before results are presented.

Rationale: there is no ground-truth cutoff for "analog"; known cases are the only available
reference for calibration.

### VII. Hackathon-Scale Simplicity

- Scope MUST favour a working, explainable prototype over completeness: limited target sites,
  limited Earth regions or a coarse global grid, and a small number of well-justified criteria.
- The search pipeline MUST follow: precomputed coarse Earth feature grid → hard-constraint
  filtering (most selective and cheapest first) → on-demand fetch of expensive data for surviving
  areas only → scoring and ranking.
- New dependencies, services or abstractions MUST be justified by a current requirement (YAGNI).

Rationale: the team is three people with a short time window; complexity that is not shipped or
explained earns nothing.

## Data and Technology Constraints

- Language: Python 3.11+. Core stack: pandas, NumPy, GeoPandas, Rasterio/rioxarray, Shapely,
  earthaccess, pystac-client, Streamlit, Folium, Plotly. Storage: GeoPackage, GeoTIFF/COG, CSV,
  JSON. Deviations require a recorded reason in the plan.
- At least one NASA data source from the challenge's official Resources section MUST be used.
- Only free data access is permitted (public, free account or free API key). Paid data or
  services MUST NOT be required.
- Credentials (Earthdata Login, API keys, tokens) MUST NOT be committed; they are supplied via
  environment variables or `~/.netrc`.
- Large raw data (cubes, DEM tiles, granules) MUST NOT be committed; it lives in a cache directory
  excluded from version control. Derived small artefacts (profiles, feature tables, results) MAY
  be committed.
- Display products (e.g. Trek WMTS tiles) MUST NOT be used as numeric inputs; numeric criteria use
  science products (DEM GeoTIFFs, summary-parameter cubes, gridded maps).
- Data-access code MUST respect provider rate limits and cache responses.

## Development Workflow and Quality Gates

- Work follows the Spec Kit flow: constitution → specify → (clarify) → plan → tasks → (analyze)
  → implement → converge. Plans MUST include a Constitution Check against Principles I–VII.
- Scoring functions and the aggregation formula MUST have unit tests with hand-computed expected
  values, including veto, `UNKNOWN` handling and weight renormalisation.
- Profiles and results MUST pass JSON Schema validation in automated checks.
- Data pipelines MUST be re-runnable from scripts with pinned inputs (dataset IDs, versions,
  bounding boxes); notebooks MAY be used for exploration but not as the only pipeline.
- Every presented ranking MUST be reproducible from committed code, profile version and a
  recorded data manifest.

## Governance

- This constitution supersedes other project practices. Where a plan or task conflicts with it,
  the constitution wins unless amended.
- Amendments are proposed as a change to this file with a Sync Impact Report, agreed by the team,
  and recorded with a new version and amendment date.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle, MINOR for
  adding a principle or materially expanding guidance, PATCH for clarifications and wording.
- Each plan's Constitution Check and each review MUST verify compliance; any justified exception
  MUST be recorded in the plan's Complexity Tracking section.

**Version**: 1.0.0 | **Ratified**: 2026-11-15 | **Last Amended**: 2026-11-15
