# CLI Contract: `analog` (also `python run.py`)

`run.py` is the main script; it forwards all arguments to `analogfinder.cli`. Every sub-command
can be run alone. Global options: `--config-dir DIR` (default `config/`), `--data-dir DIR`
(default `data/`), `--quiet`, `--verbose`, `--json` (machine-readable summary on stdout).
Human-readable progress goes to stderr; summaries to stdout.

| Command | Purpose | Key arguments | Writes |
|---|---|---|---|
| `validate` | Validate config and/or a profile | `--config`, `--profile FILE` | nothing |
| `freeze` | Compute weights, freeze profile | `--profile FILE` | `profiles/frozen/<id>@<ver>.json` |
| `extract` | Propose profile targets from planetary data (optional) | `--profile FILE`, `--criteria ID,...` | `data/cache/...` only; prints proposals |
| `check` | Pre-run source check | `--profile ID@VER` \| `--grid` | nothing |
| `grid` | Build or reuse global grid | `--force-layer LAYER_ID` (rebuild one layer into a new version) | `data/grids/<grid_id>/` |
| `screen` | Footprint values, screening + grouping | `--profile ID@VER` \| `--run RUN_ID` \| `--latest` | `data/stages/screen/<fp>/` |
| `refine` | Bound-driven refinement: terrain first, EMIT only where an area can still enter the top N (research D-024) | same, `--max-terrain-areas N`, `--max-mineral-areas N` | `data/stages/refine/<fp>/` |
| `rank` | Final scoring, ranking | same | `data/stages/rank/<fp>/` (`results.json`, `results.csv`) |
| `calibrate` | Known-analog ranks + weight stability | same | `data/stages/calibrate/<fp>/calibration.json` |
| `dedup` | Label known/new (later stage) | same | `data/stages/dedup/<fp>/results.dedup.json` |
| `site` | Generate static site for a run | `--run RUN_ID` \| `--latest` | `data/stages/site/<fp>/` (incl. `site_inputs.json`) |
| `publish` | Copy a run's site to `public/`; refused for runs flagged by calibration (research D-018) | `--run RUN_ID` \| `--latest`, `--allow-unvalidated` (publish anyway with a "not validated" banner on every page) | `public/` (replaced as a whole, atomically) |
| `run` | All stages in order, resuming completed ones | `--profile ID@VER`, `--no-dedup`, `--skip-refine` (screening preview: nothing ranked, calibrate/dedup skipped, publish refused; research D-025) | all of the above |
| `clean` | Remove old grids/runs/unreferenced cache | `--keep-grids N`, `--keep-runs N`, `--dry-run` | deletes |
| `status` | List grid versions, runs, stage-cache entries and their fingerprints, completeness | — | nothing |

`ID@VER` refers to a frozen profile; `run` and stages refuse drafts.

## Run resolution (research D-023)

Stage outputs live only in the stage cache `data/stages/<stage>/<fp>/`; a run directory
`data/runs/<run_id>/` holds `run_record.json` plus hard links (or copies) of the final files.
A stage command run on its own resolves its base run (`--run`, `--latest`, or the latest
complete run of `--profile` from `data/runs/index.json`), computes or reuses its stage, writes
a new run record if the stage combination is new, and prints `run: <run_id>` (the new id when
anything changed). Pass that id, or `--latest`, to `site` / `publish`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success (including "reused, nothing to do") |
| 1 | unexpected error (bug) — traceback with `--verbose` |
| 2 | invalid usage / arguments |
| 3 | source check failed (unreachable or login missing) |
| 4 | validation failed (config or profile) |
| 5 | frozen profile conflict (id@version exists with different hash) |
| 6 | partial result: run completed but some criteria UNKNOWN because of failed sources |
| 7 | no candidates (all rejected) — results still written |
| 8 | publish refused: run's profile is flagged for review by calibration (use `--allow-unvalidated` to override) |

## `check` output (human)

```text
SOURCE            ROLE      ROUTE      LOGIN      REACHABLE  STATUS  AFFECTS
modis-mod11c3     required  earthdata  MISSING    yes        FAIL    thermal_swing
nasa-power        required  rest       none       yes        OK      hyperarid, dry_air
era5-cds          fallback  rest       MISSING    yes        WARN    (fallback for nasa-power)
emit-l2b-min      required  earthdata  MISSING    yes        FAIL    mineral_classes, aqueous_minerals
```

Statuses (research D-023): `OK`; `FAIL` = required source unreachable or login missing with no
usable fallback → exit 3; `WARN` = fallback source unusable, or required source failing while
its fallback is `OK` ("will use fallback") → exit 0.

`--json`: `{"ok": false, "sources": [{"source_id", "role", "route", "login", "login_present",
"reachable", "status", "affects": [...], "error"}]}`.

## Credentials

Earthdata: `~/.netrc` entry for `urs.earthdata.nasa.gov` or env `EARTHDATA_USERNAME` /
`EARTHDATA_PASSWORD`. Optional Planetary Computer key: env `PC_SDK_SUBSCRIPTION_KEY`.
Copernicus CDS (only if the ERA5 climate fallback is used): `~/.cdsapirc` (url + key).
Never read from or written to project files.

## Idempotence

Running any command twice with identical inputs produces no new files and exit 0 with a
"reused" message. Stages are cached by fingerprint of their inputs (research D-011): changing a
configuration file re-runs exactly the stages that read it. Changed inputs produce new versioned directories; nothing is overwritten
except `public/`, which is replaced as a whole by `publish`.
