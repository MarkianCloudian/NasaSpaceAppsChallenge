# Quickstart & Validation Guide: Earth Analog Finder

Run guide and end-to-end validation scenarios. Commands follow [contracts/cli.md](./contracts/cli.md);
data shapes follow [data-model.md](./data-model.md). Timings marked _TBD_ are filled in by plan
sub-phase I2.

## Prerequisites

- `uv` installed; Python 3.11 is fetched by `uv` (system Python version does not matter).
- Free NASA Earthdata Login (needed for MODIS and EMIT) in `~/.netrc`:
  `machine urs.earthdata.nasa.gov login <user> password <pass>` (file mode 600), or env vars
  `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`. Never put credentials in project files.
- ~10 GB free disk for `data/`; internet access for the first run.
- Configuration files present and valid: `config/settings.json`, `config/sources.json`,
  `config/layers.json` (grid layer registry), `config/purposes.json`, `config/known_analogs.json`,
  `config/mineral_classes.json` (`uv run analog validate --config`).
- Optional: Copernicus CDS key in `~/.cdsapirc` — only needed if the POWER climate source fails
  and the ERA5 fallback is used.

## Setup

```bash
cd App
uv sync                      # creates .venv with Python 3.11 and dependencies
uv run analog --help         # or: uv run python run.py --help
uv run pytest                # offline tests (online tests skipped by default)
```

## Scenario 1 — Configuration and profile (US3)

```bash
uv run analog validate --config
uv run analog validate --profile profiles/mars-rover-jezero.json
uv run analog freeze   --profile profiles/mars-rover-jezero.json
```

Expected: validation prints `OK` with counts of scored / veto / normalized / not-comparable
criteria; freeze writes `profiles/frozen/mars-rover-jezero@1.0.0.json` with `weights` summing to
1. Running `freeze` again → "unchanged, reused" (exit 0). Editing a target and freezing under the
same version → exit 5. Broken fixtures in `tests/fixtures/profiles/` each fail with a named field
(exit 4).

## Scenario 2 — Source check (FR-016a)

```bash
uv run analog check --profile mars-rover-jezero@1.0.0
```

Expected: table of sources; with no Earthdata login, MODIS/EMIT rows show `MISSING` and the
affected criteria, exit 3. With login: all `yes`, exit 0.

## Scenario 3 — Global grid build and reuse (SC-001, SC-003)

```bash
uv run analog grid           # first time: downloads, then builds
uv run analog grid           # second time: "reused <grid_id>", seconds
uv run analog status
```

The grid is built from the layer registry `config/layers.json` (one entry per layer, builder
type + source + parameters).

Expected: `data/grids/<grid_id>/` with one GeoTIFF per layer, `manifest.json` valid against
`contracts/grid-manifest.schema.json`, `_COMPLETE`. Build time from cached inputs ≤ 10 min
(measured: _TBD_). Disk use of `data/` < 10 GB (measured: _TBD_).

## Scenario 4 — Full run (US1, SC-002, SC-004, SC-005)

```bash
uv run analog run --profile mars-rover-jezero@1.0.0
uv run analog run --profile mars-rover-jezero@1.0.0   # repeat → reused, identical
```

Expected: `data/runs/<run_id>/` with `results.json` (valid against
`contracts/results.schema.json`), `results.csv`, `run_record.json`, `calibration.json`, `site/`.
Every ranked candidate has score, confidence, limiting criterion, `footprint` (circle of the
profile radius around its best cell) and a full per-criterion table. `run_record.json` shows
`percentile_population` {name, cells}, a fingerprint per stage and `refinement` {stop,
proven_top, …}: `bound_reached` means the top N are proven complete; `cap_reached` means the
refinement cap was hit first (the site says so). Second run: same `run_id`,
nothing new written. Cached full run ≤ 10 min (measured: _TBD_);
first run ≤ 60 min (measured: _TBD_).

Resume check (US1 scenario 6): interrupt during `refine` (Ctrl-C), re-run → log shows
`check, grid, screen: reused` and continues at `refine`.

Partial re-run check (stage fingerprints): add a site to `config/known_analogs.json` and re-run
→ log shows `screen, refine, rank: reused`, only `calibrate`, `dedup`, `site` recomputed, new
`run_id`; the previous run directory is unchanged.

## Scenario 5 — Calibration (US4, SC-006)

Open `data/runs/<run_id>/calibration.json` (also on `site/about.html`). Expected: relevant
known sites listed with their own circle (`footprint` centred on the site), rank and score
(vetoed sites show `rejected_by`); at least one within top 20%, otherwise `flag_for_review: true`
with `flag_reasons`; stability shares for top candidates, identical on repeated runs.

## Scenario 6 — Site (US2, SC-008, SC-009)

```bash
uv run analog site --run <run_id>
uv run analog publish --run <run_id>
uv run python -m http.server -d public 8000   # open http://localhost:8000
uv run pytest tests/site
```

If the run is flagged by calibration, `publish` exits 8 and leaves `public/` unchanged; use
`uv run analog publish --run <run_id> --allow-unvalidated` to publish anyway — every page then
shows the "Not validated against known analogs" banner with the reasons.

Expected: map + ranked table; candidate pages show all fields from
[contracts/site.md](./contracts/site.md). With JavaScript disabled in the browser the table and
candidate pages remain fully readable. `tests/site` confirms < 2 MB initial download and no
external font/script/style requests. Deploy: commit `public/` and push to `main` — the
`.github/workflows/pages.yml` workflow publishes it to GitHub Pages; for Cloudflare Pages set no
build command and output directory `public`.

## Scenario 7 — Deduplication (US5, later stage, SC-011)

```bash
uv run analog dedup --profile mars-rover-jezero@1.0.0   # prints "run: <new_run_id>"
uv run analog site --latest                              # or: --run <new_run_id>
```

Expected: candidates inside a known site's radius labelled `known_analog` with the site name,
others `new_candidate`; site highlights new candidates and lists known ones separately; at least
3 new candidates or an explicit reason in the run summary.

## Scenario 8 — Add a second profile by configuration only (SC-007)

Copy the Mars profile to `profiles/mars-landing-test.json`, change `profile_id`, `purpose`
(add the purpose to `config/purposes.json` if new), reference site and targets; `validate` →
`freeze` → `run`. Expected: runs with zero code changes; its site section is separate.

## Housekeeping

```bash
uv run analog clean --dry-run          # shows what would be removed
uv run analog clean --keep-runs 3
```

Expected: only unreferenced/old items removed; anything referenced by kept runs stays.
