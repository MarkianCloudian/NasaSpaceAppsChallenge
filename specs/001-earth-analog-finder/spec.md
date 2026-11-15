# Feature Specification: Earth Analog Finder

**Feature Branch**: `001-earth-analog-finder` (no git repository yet; directory name only)

**Created**: 2026-11-15

**Status**: Draft (clarifications resolved 2026-11-15)

**Input**: User description: "A small hackathon project that aims to solve the challenge of finding places on Earth that are yet unknown to be matching or being similar to locations on Mars/Moon. The matching is made via retrieval and comparison pf various Earth datasests' data with created JSON etalon profiles for Mars/Moon locations(and possibly on already known like Atacama dessert), this profiles consist of values and weights of criterias like thermal, biological, terrain etc. (right now without any machine learning)  and by a certain  algorithm the numerical match and deviation from etalon profile data and Earth data is calculated. The working version of app  should be available to run as a script(not singular but could the main one to execute other in a directory) for data analysis via API and presentation of the results in an interactive non-javascript(or without heavy usage, vaniall JS without nerdy fonts') page (that could be deployed via cloudflare or hithuub pages) that serves as a simplified ram-friendly map wchich will show new locations on Earth, the brief description on how it was calculated and how much it deviates from original etalon prfile criteria values."

## Clarifications

### Session 2026-11-15

- Q: Earth search scope? → A: A precomputed coarse grid over all eligible land on Earth, built
  once and cached; building it from already-downloaded inputs must take no more than 10 minutes,
  and later runs reuse it. Detailed data is fetched only for areas that pass screening.
- Q: Reference profiles in the first version? → A: One Mars reference profile only, built fully,
  to prove the whole pipeline end to end. Adding further Mars/Moon profiles and known Earth analog
  sites MUST be possible through configuration only, without changing program logic.
- Added by user: removing (deduplicating) candidates that coincide with already-known Earth
  analogs of Mars/Moon (e.g. Devon Island) is a later stage, run after the analysis and criterion
  comparison.
- Q: How should the global Earth grid be assembled? → A: One layer per grid-scale criterion,
  each from the dataset named in configuration, all resampled onto one shared cell grid (same
  cell size, extent and land mask) and stacked. Marked for future review; see `research.md`
  (D-001).
- Q: How should the grid, downloaded data and run results be stored across repeated runs? → A:
  Three separate versioned stores, nothing overwritten: an immutable download cache keyed by
  source, version and area; one directory per grid version (one file per layer plus a manifest);
  one directory per run. Same inputs reuse everything; changed inputs create a new version next
  to the old; a cleanup command keeps the last N. See `research.md` (D-002).
- Q: How should the team enter criteria weights? → A: The team ranks the 8 categories (purpose
  configuration) and the criteria within each category (profile); the system computes numeric
  weights with the recorded method (default rank-order centroid), multiplies the two levels and
  stores the result in the frozen profile. Direct numeric entry is allowed as method "direct". An
  interactive weight slider with locking is recorded as a future option in `research.md` (D-003).
- Q: How strictly should each external data source be documented and checked before a run? → A:
  Every source has a configuration entry (provider, dataset id and version, access route, login
  need, request unit, format, rate limit, licence/citation, optional fallback mirror); only routes
  publicly documented by the provider are allowed, including documented scripted downloads; a
  check stage verifies every needed source before a run; sources without a programmatic route may
  only feed hand-entered profile values with their source recorded. See `research.md` (D-004).
- Analysis remediation (/speckit-analyze C1): Earth values are computed over the same circular
  footprint as the Mars target (profile reference radius) around each evaluated location, at
  screening and final scoring; candidate areas only group locations for presentation. See
  `research.md` (D-017).
- Analysis remediation (C2): publishing results of a profile flagged by calibration is refused
  unless explicitly overridden, and an overridden site carries a "not validated" banner. See
  `research.md` (D-018).
- Analysis remediation (I2): grid layers are defined in configuration (layer registry); a layer's
  source can be swapped by configuration when an existing layer builder type handles its format.
  See `research.md` (D-019).
- Analysis remediation (I1, option B): scale-dependent grid criteria take their baseline from
  the layer registry and validation checks that the profile states the same baseline; the Mars
  target is computed at that baseline. See `research.md` (D-020).
- Analysis remediation (second review, A1/A2/A3/N1–N4/A8/U1/U5): per-stage fingerprints over the
  inputs each stage reads; ERA5 (Copernicus CDS) replaces POWER point requests as the climate
  fallback; explicit file readers (h5py, rasterio ENVI); grid fixed at 0.05° in v1; known sites
  calibrated on their own footprint; footprint statistics by neighbour gathering with an early
  benchmark; extra settings keys; fallback also on "no data here"; GitHub Pages via an Actions
  workflow. See `research.md` (D-008, D-011, D-017, D-022).
- Analysis remediation (fourth review, Q1/Q2): running without refinement is a labelled
  screening preview (nothing ranked, never published); known-site ranks are conservative ranks
  against final scores and upper bounds. See `research.md` (D-025).
- Analysis remediation (P4, variant d+e+f): refinement order and stopping are driven by an
  optimistic upper bound on each area's final score (best-first search), tightened by cheap
  information (EMIT coverage from metadata, regional slope as a hint for rover-scale slope), with
  cheap terrain refinement before expensive EMIT refinement and a configured cap. See
  `research.md` (D-024).
- Analysis remediation (I3, option C): each profile declares the Earth reference population for
  percentiles (default: cells passing its hard constraints); percentiles are computed per run on
  footprint values. See `research.md` (D-021).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run an analysis for the Mars reference profile (Priority: P1)

A team member starts the analysis for the Mars reference profile (e.g. "Mars, rover expedition,
Jezero crater delta") with a single main command. The analysis (1) builds or reuses the global
coarse Earth grid, (2) applies the profile's hard constraints and vetoes to screen out unsuitable
land, (3) fetches detailed data only for the surviving areas, (4) scores each candidate criterion
by criterion, and (5) writes a ranked list of Earth candidate areas with per-criterion scores,
deviations, confidence and the limiting criterion.

**Why this priority**: This is the scientific core. Without a ranked, explained candidate list
there is nothing to show; with it alone the team already has a usable research result.

**Independent Test**: Run the main command for the Mars profile and check that a ranked result
file is produced in which every candidate has an overall score, a confidence value, a score and a
deviation for every scored criterion, and its limiting criterion.

**Acceptance Scenarios**:

1. **Given** a valid reference profile and network access, **When** the user runs the main
   command, **Then** the system produces a ranked candidate list and a run record naming the
   profile version, data sources and settings used.
2. **Given** a candidate whose score on a veto criterion is below that criterion's veto threshold,
   **When** scoring runs, **Then** the candidate is rejected regardless of its other scores, the
   rejecting criterion is recorded, and its remaining criteria need not be evaluated.
3. **Given** a criterion with no Earth data (or insufficient coverage) for a candidate, **When**
   scoring runs, **Then** that criterion is marked unknown (not a mismatch), its weight is spread
   over the known criteria, and the candidate's confidence is lowered accordingly.
4. **Given** a candidate whose confidence is below the profile's minimum confidence, **When**
   ranking runs, **Then** it is not ranked and is listed separately as "insufficient data".
5. **Given** the global grid was already built from the same inputs and settings, **When** the
   user runs the analysis again, **Then** the grid and all retrieved data are reused, not rebuilt
   or downloaded again, and the ranking is identical.
6. **Given** one stage fails part-way, **When** the user re-runs the main command, **Then**
   completed stages are not repeated and the run continues from the failed stage.

---

### User Story 2 - Explore results on a lightweight map page (Priority: P2)

A judge, scientist or team member opens a static web page that shows the candidate areas on a
simple map and in a ranked list. Selecting a candidate shows its overall score, confidence,
limiting criterion and, for every criterion, the Earth value, the reference target, the deviation
and the score, plus where the analogy breaks down and a short plain-language explanation of how
the score was calculated. The page works on a low-memory laptop or phone and can be published on
free static hosting.

**Why this priority**: The challenge is judged on what people can see and understand. The page
turns the P1 result into something explainable, but depends on P1 output.

**Independent Test**: Generate the page from a sample result file, open it from a static host (or
locally, without any server-side component) on a low-memory device, and confirm that candidates,
details, deviations and the method explanation are visible and that no external fonts or heavy
script libraries are requested.

**Acceptance Scenarios**:

1. **Given** a result file, **When** the page is generated, **Then** it consists only of static
   files that can be uploaded unchanged to a free static host.
2. **Given** the published page, **When** a visitor selects a candidate, **Then** they see the
   overall score, confidence, limiting criterion, a per-criterion table (Earth value, target,
   deviation in the criterion's unit and as a share of tolerance, score, comparison mode, data
   source) and the analogy-limits statement.
3. **Given** the published page, **When** a visitor opens the method section, **Then** they see
   a brief plain-language explanation of the scoring (screening, veto check, per-criterion scores,
   weighted combination, confidence) and a summary of the reference profile and its weights.
4. **Given** a browser with scripting disabled, **When** the page is opened, **Then** the ranked
   list with each candidate's scores and deviations is still readable; only map interaction is lost.
5. **Given** results for more than one profile (future), **When** the visitor switches profile,
   **Then** only that profile's candidates are shown, and scores from different profiles are never
   presented side by side as comparable.

---

### User Story 3 - Create, validate and freeze a reference profile (Priority: P3)

A team member creates the Mars reference profile, or adds a new Mars/Moon profile later, by
writing configuration only. The profile states body, purpose, reference site and footprint,
criteria (with targets, tolerances, vetoes, weights, comparison modes and data sources) and the
weight method. Target values are filled in fully before any Earth analysis, either by hand from
literature or by extracting statistics from planetary datasets over the reference footprint. A
validation step reports every problem; a valid profile is frozen under a version.

**Why this priority**: Profiles are the input to everything. One hand-made profile is enough for
P1/P2, but validation and freezing make results trustworthy and further profiles cheap to add.

**Independent Test**: Validate one correct and several deliberately broken profiles and check that
the correct one passes and each broken one fails with a specific, readable message; then add a
second profile purely through configuration and confirm the analysis accepts it without changes to
program logic.

**Acceptance Scenarios**:

1. **Given** a profile whose scored-criterion weights sum to 0.9, **When** validation runs,
   **Then** it fails and names the profile and the weight total.
1a. **Given** a purpose configuration ranking the 8 categories and a profile ranking criteria
   within each category, **When** the profile is frozen, **Then** the stored weights equal the
   rank-order centroid values of both levels multiplied together and sum to 1.
2. **Given** a criterion that is not reproducible on Earth but is marked as an absolute
   comparison, **When** validation runs, **Then** it fails and asks for "normalized" or "not
   comparable".
3. **Given** a profile that overrides a purpose-level category weight without a reason, **When**
   validation runs, **Then** it fails and names the overridden category.
4. **Given** a valid profile, **When** validation runs, **Then** it passes and reports profile id,
   version, and counts of scored, veto, normalized and not-comparable criteria.
5. **Given** a profile version already used in a recorded run, **When** a target, tolerance, veto
   or weight is changed without a new version, **Then** the analysis refuses to run.
6. **Given** a new profile file for another body or purpose placed in the profiles configuration,
   **When** the analysis is started for it, **Then** it runs without any change to program logic.

---

### User Story 4 - Calibrate scoring against known analogs (Priority: P4)

The team keeps a configurable list of recognised terrestrial analog sites (e.g. Lake Salda,
Atacama Desert, Río Tinto, Haughton crater on Devon Island, Antarctic Dry Valleys). After a run the
system reports where the known sites relevant to the profile rank, and checks how stable the
ranking is when the weights are slightly varied. This shows whether the scoring behaves sensibly.

**Why this priority**: There is no ground truth for "analog"; known sites and a weight-stability
check are the only practical sanity test. It refines P1 rather than enabling it.

**Independent Test**: Run the Mars profile with a relevant known analog inside the search scope
and check that the calibration report lists that site's rank, score and limiting criterion, plus a
ranking-stability figure.

**Acceptance Scenarios**:

1. **Given** a known-analog list, **When** a run completes, **Then** a calibration report lists
   each relevant known site inside the scope with its rank, score and limiting criterion.
2. **Given** a relevant known analog that ranks outside the profile's upper results, **When** the
   report is produced, **Then** the profile is flagged for review (tolerances or weights to be
   revisited as a new profile version).
3. **Given** a completed run, **When** the weight-stability check runs, **Then** the report states,
   for each top candidate, how often it stays in the top group when weights are randomly varied
   within a configured range.

---

### User Story 5 - Deduplicate against known Earth analogs (Priority: P5, later stage)

After the analysis and criterion comparison are complete, a final stage compares the ranked
candidates with the known-analog list (e.g. Devon Island, Atacama) and separates candidates that
coincide with already-known analogs from genuinely new ones, so the page highlights places not yet
recognised as analogs.

**Why this priority**: The challenge goal is to find places not yet known as analogs, but this
stage only filters the output of P1 and can be added after the pipeline works end to end.

**Independent Test**: Run the deduplication stage on a result file containing one candidate inside
a known site's radius and one outside, and check that the first is labelled "known analog" (with
the matched site's name) and the second "new candidate".

**Acceptance Scenarios**:

1. **Given** a ranked result and a known-analog list, **When** deduplication runs, **Then** each
   candidate within a known site's radius is labelled "known analog" with the site name, and all
   others are labelled "new candidate".
2. **Given** deduplicated results, **When** the page is generated, **Then** new candidates are
   highlighted and known analogs are shown separately (not removed), so visitors can compare them.
3. **Given** deduplication has not been run, **When** the page is generated, **Then** candidates
   carry no known/new label and the page states that deduplication was not applied.

---

### Edge Cases

- A data source is unreachable, rate-limited, or requires a login that is not configured: the
  pre-run check reports it before any work starts; if it fails later during a run, the run tries
  the fallback mirror, then names the source and affected criteria, continues with the rest, and
  marks those criteria unknown.
- Every candidate is rejected by screening or vetoes: the run finishes, reports zero candidates and
  the count rejected per criterion; the page shows this message instead of an empty map.
- Many adjacent grid cells match: they are grouped into one candidate area, so the map is not
  flooded with near-duplicates.
- A very large number of candidates qualify: only the top N (configurable) go to the page; the full
  list stays in the result file.
- The analysis is run without refinement (screening preview): areas are listed by screening
  score as "screened only" with their upper bound, nothing is ranked, the site shows a "screening
  preview" banner, and publishing is refused.
- Refinement hits its cap before the top results are proven complete: the run finishes, the run
  record says `cap_reached` with how many of the top N are proven, and the site shows "top results
  not proven complete".
- A criterion's planetary value is physically impossible on Earth (e.g. vacuum, lunar thermal
  extremes): it is either "not comparable" (shown, not scored) or scored by Earth percentile and
  labelled "relative".
- A criterion's value cannot be measured at the coarse grid scale (e.g. rover-scale slope,
  mineralogy): it is evaluated only during refinement, and the candidate's final score uses the
  refined value; screening uses only criteria declared valid at grid scale.
- A planetary "not detected" value comes from an area outside instrument coverage: it is treated as
  unknown, not as absent.
- A profile still contains placeholder target values: the run proceeds, but every output and the
  page carry a visible "placeholder values" label.
- The scope includes oceans, ice sheets, cities or farmland not wanted by the profile: these are
  excluded by the profile's search constraints before scoring.
- A run's profile is flagged by calibration: the site is generated for review, but publishing is
  refused until the profile is revised as a new version or the user explicitly overrides, in which
  case every page carries a "not validated" banner.
- The grid's input data or settings change: a new grid version is built next to the old one;
  otherwise the existing grid version is reused.
- A build or run is interrupted (crash, closed laptop): the partial version is not treated as
  complete; the next run resumes or rebuilds it.
- Disk space runs low: the cleanup command frees old versions while keeping everything referenced
  by the kept runs.
- One grid layer's source is unavailable during a build: the other layers are built; criteria
  depending on the missing layer are unknown for all cells until it is rebuilt.

## Requirements *(mandatory)*

### Functional Requirements

**Reference profiles and configuration**

- **FR-001**: System MUST read reference profiles, purpose definitions, data-source definitions,
  grid layer definitions and the known-analog list from configuration files; adding a profile,
  purpose, data source mapping, grid layer of a supported type or known site MUST NOT require
  changes to program logic.
- **FR-002**: Each profile MUST have a profile id and version and declare: body, purpose,
  reference site (location and footprint radius), search constraints (e.g. latitude range,
  excluded land cover), minimum confidence, weight method and criteria.
- **FR-003**: Each criterion MUST declare: id; category (one of the 8 challenge analogy
  categories); measured quantity; statistic (e.g. annual min/max, median, 90th percentile);
  unit; target (range with optional open bounds, set of classes, or yes/no); lower and upper
  tolerance; optional veto threshold; weight; comparison mode (absolute, normalized, not
  comparable); scoring rule; evaluation scale (grid screening, refinement, or both); value status
  (measured or placeholder); known uncertainty where available; and data sources for the
  planetary and the Earth side.
- **FR-004**: Scale-dependent criteria (e.g. slope, roughness) MUST declare the spatial baseline
  at which they are computed, equal to the baseline of the Earth layer or refinement method that
  supplies them, and the planetary target MUST be computed at the same baseline; spectral/mineral criteria MUST declare the parameters or classes
  valid on both bodies and the mapping between planetary and Earth mineral names.
- **FR-005**: A criterion MUST be kept in a profile only if it is relevant to the purpose,
  measurable on both bodies (or marked not comparable) and not redundant with another kept
  criterion; removed or merged criteria MUST be recorded with a reason.
- **FR-006**: Weights MUST be set in two levels: purpose-level weights per analogy category (shared
  by all profiles of that purpose) multiplied by within-category weights per criterion. Weights
  MUST NOT be fixed in program logic; they come only from configuration. The team enters a rank
  order of the 8 categories (purpose configuration) and of the criteria within each category
  (profile); the system MUST compute numeric weights from the ranks using the recorded method
  (default: rank-order centroid; ties share the average of their positions), multiply the two
  levels, and store the resulting weights in the frozen profile. Direct numeric entry MUST also be
  accepted, recorded as method "direct". Any profile-level override of a category weight MUST
  include a reason.
- **FR-007**: Weights of scored criteria MUST sum to 1 (within rounding) after excluding
  not-comparable criteria.
- **FR-008**: System MUST validate profiles before analysis and report every error with the profile
  id and field at fault; analysis MUST NOT start on an invalid profile.
- **FR-009**: System MUST refuse to analyse a changed profile under a version already used in a
  recorded run; Earth results MUST NOT change a profile's targets.
- **FR-010**: System SHOULD provide a stage that extracts a profile's target statistics from
  planetary datasets over the reference footprint; hand-entered targets MUST also be accepted.
- **FR-011**: The first version MUST ship one complete Mars reference profile with measured (not
  placeholder) targets for every scored criterion where planetary data allows.

**Global Earth grid**

- **FR-012**: System MUST build a coarse grid covering all eligible land on Earth on a fixed 0.05°
  cell grid in v1 (the native MODIS climate-modelling grid; the cell size is recorded in settings
  and in each grid manifest; other sizes are a later extension that needs a resampling step),
  holding the grid-scale criterion values (e.g. regional terrain, surface
  temperature statistics, vegetation, land cover, aridity). The grid MUST be assembled from
  multiple datasets as separate layers: each layer comes from one configured source dataset, is
  resampled onto one shared cell definition (cell size, extent, land mask), and records its source
  and resampling method. Each layer MUST be declared in configuration (layer id, builder type,
  source, parameters, outputs). Replacing a layer's source with one that an existing builder type
  can read MUST require configuration changes only; a source in a new format MAY require a new
  builder type. A missing or failed layer MUST leave the other layers usable.
- **FR-013**: Building the grid from already-downloaded inputs MUST take no more than 10 minutes.
  Each grid build MUST be stored as its own grid version (one directory: one file per layer plus a
  manifest of sources, versions, cell definition and build date), identified by its layer settings
  and cell size. A build with settings identical to an existing grid version MUST reuse it and
  create nothing new; changed settings MUST create a new grid version without altering existing
  ones.
- **FR-014**: Downloaded inputs MUST be stored in a download cache keyed by source, dataset
  version and area; cached files MUST never be modified, and a request already in the cache MUST
  NOT be downloaded again.
- **FR-014a**: Each run MUST be stored in its own run directory (results, run record, calibration
  report, generated page) that references the grid version and profile version it used; runs MUST
  NOT overwrite each other. A run with the same profile version, grid version and settings as an
  existing run MUST reuse that run instead of creating a duplicate. Each stage MUST be identified
  by the inputs it reads (including the configuration files it uses, such as the known-analog
  list or the mineral crosswalk); a change to such an input MUST re-run exactly the stages that
  read it and reuse all others.
- **FR-014b**: An interrupted build, download or run MUST NOT leave a partial version that later
  runs treat as complete; partial output is discarded or resumed, never reused as finished.
- **FR-014c**: A cleanup command MUST remove old grid versions, runs and unused cached downloads,
  keeping the last N (configurable) and never removing anything referenced by a kept run.

**Analysis and scoring**

- **FR-015**: System MUST provide one main command that runs all stages in order (source check,
  grid build/reuse, screening, refinement data retrieval, scoring, ranking, calibration, optional deduplication,
  page generation); each stage MUST also be runnable on its own.
- **FR-016**: System MUST retrieve Earth data programmatically from public data services, including
  at least one NASA data source from the challenge's official resource list. Every data source
  MUST have a configuration entry declaring: provider, dataset id and version, access route
  (query API, catalogue search, or direct file download), login requirement (none, free account,
  free key), unit of request (tile, area or point), file format, rate limit, licence and citation,
  and an optional fallback mirror. Only access routes publicly documented by the provider are
  allowed; documented scripted file downloads count as programmatic. Sources requiring payment
  MUST NOT be used.
- **FR-016a**: A check stage MUST verify, before any download or run, that every source needed by
  the selected profile and grid is reachable and that required logins are configured, and MUST
  report each failing source with the criteria it affects. The check MUST be runnable on its own
  and is run automatically by the main command.
- **FR-016b**: Sources with no documented programmatic route MAY be used only for hand-entered
  profile target values, each recorded with the source name, version and access date; they MUST
  NOT be used for Earth-side retrieval.
- **FR-016c**: Retrieval MUST respect each source's declared rate limit, retry transient failures
  a bounded number of times, and switch to the declared fallback mirror when the primary route
  fails.
- **FR-017**: For each candidate and criterion, the Earth value MUST be computed using the same
  quantity, statistic, unit, spatial footprint and baseline as the profile criterion. Measurements
  of different kinds (e.g. element abundances vs mineral detections) MUST NOT be compared directly
  without a documented bridging method.
- **FR-017a**: Every Earth criterion value MUST be computed over a circular footprint with the
  profile's reference radius around the evaluated location, using the criterion's declared
  footprint statistic (e.g. mean, max, 90th percentile), so that it covers the same area as the
  planetary target. This applies to screening and to final scoring; grid cells inside the
  footprint are weighted by their area. If the reference radius is smaller than one grid cell,
  grid-scale values MUST be taken from the single containing cell and this MUST be noted in the
  result.
- **FR-018**: Screening MUST apply the profile's hard constraints and grid-scale veto criteria to the
  whole grid, cheapest and most selective first; detailed data MUST be fetched only for areas that
  pass.
- **FR-018a**: Detailed data MUST be fetched in order of each area's best achievable final score
  (an optimistic upper bound computed from its grid-scale scores, cheap metadata and optimistic
  estimates for not-yet-measured criteria), cheaper detailed data (fine terrain) before more
  expensive data (mineral spectra), and refinement MUST stop as soon as no unrefined or partly
  refined area can still enter the presented top results, or when a configured cap is reached.
  Whether the presented top results are proven complete or limited by the cap MUST be recorded
  in the run record and shown on the site; areas never refined are kept as "screened only" with
  their upper bound.
- **FR-019**: Each criterion comparison MUST give a score between 0 and 1 using the criterion's
  scoring rule: 1 inside the target range, falling to 0 as the deviation reaches the tolerance
  (separate lower and upper tolerance); class targets scored by overlap of class sets, with
  partial credit for related classes; yes/no targets scored as match or mismatch.
- **FR-020**: Where uncertainty of the planetary and Earth values is known, it MUST widen the
  effective tolerance of the comparison.
- **FR-021**: Each criterion result MUST record the deviation from the target in the criterion's
  unit and as a share of its tolerance.
- **FR-022**: A candidate MUST be rejected when any criterion score is below that criterion's veto
  threshold, regardless of other scores; the rejecting criterion MUST be recorded.
- **FR-023**: The overall score MUST be the weighted geometric mean of the known criterion scores
  (weights renormalised over known criteria), so that a very low criterion score lowers the overall
  score strongly and is not offset by high scores elsewhere.
- **FR-024**: Criteria without data or sufficient coverage MUST be marked unknown (never a
  mismatch); confidence MUST equal the sum of weights of criteria with data; candidates below the
  profile's minimum confidence MUST be listed separately, not ranked.
- **FR-025**: Normalized-mode criteria MUST be scored by the Earth value's percentile within the
  profile's declared reference population (default: all cells passing the profile's hard search
  constraints; alternatives: all land, ice-free land), computed per run on footprint values
  (FR-017a), area-weighted, against the profile's target percentile; the population used MUST be
  recorded in the run record and shown on the site, and these criteria MUST be labelled "relative";
  not-comparable criteria MUST be shown but excluded from the score.
- **FR-026**: Each candidate MUST report its limiting criterion (lowest score) and a statement of
  where the analogy breaks down (including all not-comparable and normalized criteria).
- **FR-027**: Adjacent qualifying grid cells MUST be grouped into candidate areas for presentation;
  each area is scored at its best location using the footprint values of FR-017a (never as an
  average over the whole area); a configurable number of top candidates per profile MUST be kept
  for presentation.
- **FR-028**: System MUST write a run record: profile id and version, data sources and versions,
  grid settings, scope, settings, date, and counts (evaluated, rejected per criterion, insufficient
  data, ranked).
- **FR-029**: Re-running with the same profile version, inputs and settings MUST give an identical
  ranking.
- **FR-030**: Scores from different profiles MUST NOT be ranked together or presented as directly
  comparable.

**Calibration**

- **FR-031**: System MUST produce a calibration report listing each relevant known analog inside
  the scope with conservative rank (as defined in SC-006), score and limiting criterion, and flag
  the profile if none ranks in the
  profile's upper results or if no relevant known analog lies in scope (with the reason recorded).
- **FR-031a**: Publishing the site of a run whose profile is flagged for review MUST be refused
  unless the user explicitly overrides it; an overridden site MUST show a visible "not validated
  against known analogs" banner on every page.
- **FR-032**: System MUST report ranking stability under random variation of weights within a
  configured range (share of variations in which each top candidate stays in the top group).

**Deduplication (later stage)**

- **FR-033**: As a stage after scoring and ranking, the system MUST label each candidate within a
  known analog's radius "known analog" (with the site name) and all others "new candidate"; known
  analogs are kept and shown separately, not deleted.

**Results page**

- **FR-034**: The results page MUST be generated as static files only, publishable unchanged to
  free static hosting, with no server-side component and no live data requests.
- **FR-035**: The page MUST show candidates on a simple map and in a ranked list, and allow choosing
  the reference profile when more than one exists.
- **FR-036**: For each candidate the page MUST show: name or coordinates, overall score, confidence,
  limiting criterion, known/new label (if deduplication ran), a per-criterion table (Earth value,
  target, deviation in unit and as share of tolerance, score, comparison mode, data source), and the
  analogy-limits statement.
- **FR-037**: The page MUST include a brief plain-language explanation of how scores were
  calculated and a summary of the reference profile and its weights.
- **FR-038**: The ranked list and candidate details MUST remain readable with scripting disabled;
  any scripting MUST be small and self-contained; the page MUST NOT load external fonts or large
  third-party libraries.
- **FR-039**: Placeholder profile values and relative (normalized) comparisons MUST be visibly
  labelled on the page.

### Key Entities *(include if feature involves data)*

- **Purpose**: intended use (landing, rover expedition, permanent base, astrobiology, ...); holds
  the category weights shared by all profiles of that purpose.
- **Reference Profile**: frozen description of one Mars/Moon location for one purpose; id, version,
  body, purpose, reference site and footprint, search constraints, minimum confidence, weight
  method, overrides with reasons, criteria.
- **Criterion**: one comparable characteristic in a profile; category, quantity, statistic, unit,
  baseline, target, tolerances, veto, weight, comparison mode, scoring rule, evaluation scale, value
  status, uncertainty, class mapping (for minerals), data sources.
- **Data Source**: external dataset used for a criterion or grid layer; provider, name,
  version/collection id, resolution, coverage, access route, login requirement, request unit,
  format, rate limit, licence and citation, fallback mirror.
- **Earth Grid Cell**: one coarse cell of eligible land with its grid-scale criterion values.
- **Grid Layer**: one grid-scale quantity on the shared cell grid, declared in the layer
  registry configuration; builder type, source dataset and version, parameters, resampling
  method, units, build date; one layer per grid-scale criterion quantity.
- **Earth Candidate**: a grouped area of qualifying cells evaluated against a profile; extent,
  criterion results, overall score, confidence, limiting criterion, rejection reason, known/new
  label.
- **Criterion Result**: one candidate vs one criterion; Earth value, deviation (unit and share of
  tolerance), score, state (known, unknown, not comparable, relative), data source.
- **Known Analog Site**: recognised terrestrial analog; name, location, radius, bodies/purposes it
  is known for, literature reference.
- **Run Record**: profile version, grid version, data sources and versions, grid settings, scope,
  settings, timestamp, counts.
- **Grid Version**: one stored build of the grid; identified by layer settings and cell size;
  holds its layers and a manifest; immutable once complete.
- **Cached Download**: one raw file from a data source; keyed by source, dataset version and area;
  immutable.
- **Calibration Report**: known-site ranks and ranking stability for one run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Building the global Earth grid from already-downloaded inputs takes no more than 10
  minutes on a standard team laptop; later runs reuse it with no rebuild.
- **SC-002**: With the grid and data cached, a complete run for the Mars profile (screening to page)
  finishes in under 10 minutes; the first full run, including downloads, finishes in under 60
  minutes on a typical home connection.
- **SC-003**: Cached inputs and the grid together fit in under 10 GB of disk space.
- **SC-004**: 100% of ranked candidates show score, deviation and data source for every scored
  criterion, plus confidence and limiting criterion.
- **SC-005**: Two runs with the same profile version, inputs and settings give identical rankings
  (100% of positions match).
- **SC-006**: At least one relevant known analog inside the scope has a conservative rank within
  the top 20% of areas that passed screening (conservative rank = 1 + number of areas whose final
  score or, if not fully refined, upper bound exceeds the site's score), or the profile is flagged
  for review.
- **SC-007**: A second profile can be added and analysed by editing configuration only, with zero
  changes to program logic.
- **SC-008**: The published page's initial download is under 2 MB, it opens in under 3 seconds on a
  typical home connection and stays usable on a device with 4 GB of RAM.
- **SC-009**: The page makes zero requests for external fonts or large third-party libraries, and
  the ranked list is fully readable with scripting turned off.
- **SC-010**: In a hallway test, at least 4 of 5 first-time viewers can say within 2 minutes why the
  top candidate ranked first and which criterion deviates most.
- **SC-011**: After deduplication, each run yields at least 3 "new candidate" areas for the profile,
  or the run reports why fewer qualified.

## Assumptions

- Users are the hackathon team (running the analysis) and judges, scientists and the public
  (viewing the page); the page has no accounts or login.
- First version: one Mars profile (default: rover expedition at Jezero crater delta, from
  `sample-edited.json`), extended with tolerance, veto, weight-method, baseline and evaluation-scale
  fields. Moon profiles and further Mars profiles come later through configuration.
- The coarse grid cell size is fixed at 0.05° (about 5.5 km) in v1, which keeps global land at a few
  million cells and the 10-minute build target realistic. Fine-scale criteria (rover-scale slope
  and roughness, mineralogy) are evaluated only in refinement for screened areas, because they
  cannot be measured meaningfully at grid scale.
- Grid-scale inputs are global, already gridded products (regional elevation, land-surface
  temperature climatology, vegetation, land cover, climate); their one-off download may take longer
  than 10 minutes and is excluded from the 10-minute build target.
- Eligible land excludes oceans, permanent water and, unless the profile allows them, ice sheets,
  urban areas and cropland.
- Default tolerances, vetoes and weights are set by the team using the recorded weight method and
  then checked through calibration; there is no universal cutoff for "analog".
- Known-analog list is compiled by the team from literature; default known-site radius is 50 km
  unless a site sets its own.
- Analysis runs on team laptops with internet access; free accounts (e.g. NASA Earthdata Login) may
  be needed for some sources and are configured by each member outside project files.
- No machine learning is used for scoring in this version.
- The page is regenerated after each run; it does not update itself or call data services.
- The map background is a lightweight, freely licensed simplified outline or tile layer that needs
  no heavy libraries.
