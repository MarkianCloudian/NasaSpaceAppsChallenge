# Earth Analog Finder

NASA Space Apps Challenge 2026 · team February Stars

Earth Analog Finder searches the Earth's land surface for places that resemble a chosen location
on Mars or the Moon. The first version compares Earth with one Mars site, the Jezero crater delta
explored by the Perseverance rover, for the purpose of a rover expedition. The results are
published as a static website with a world map of candidate areas and, for each area, how closely
it matches the Mars site and where it differs.

## How it works

1. **Reference profile.** The Mars site is described in a JSON profile
   (`profiles/mars-rover-jezero.json`): measurable criteria such as dryness, vegetation, bare
   ground, day–night temperature swing, slope, surface roughness and minerals, each with a Mars
   target value, a tolerance, an optional veto and a weight. Targets come from Mars orbital data,
   the Mars Climate Database and published studies.
2. **Earth grid.** Public Earth datasets (NASA MODIS, NASA POWER, NOAA ETOPO and others) are
   downloaded and placed on one global grid of 0.05° cells (about 5 km).
3. **Screening.** For every place on land, each criterion is summarised over a circle the same
   size as the Mars reference area (20 km radius), places that fail a veto are removed, and each
   criterion is scored from 0 to 1 by its deviation from the Mars target.
4. **Refinement and ranking.** The best areas are re-measured with 30 m terrain data and, where
   available, NASA EMIT mineral maps. The final match is a weighted geometric mean of the
   criterion scores, reported with a confidence value and the criterion that limits the match.
   Properties Earth cannot reproduce (gravity, air pressure) are listed as limits of the analogy.
5. **Website.** The ranked results are rendered as plain HTML pages with an SVG map and published
   on GitHub Pages.

New Mars or Moon sites can be added as new profile files, without changing the code.

## Running it

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/). NASA datasets need a free
[Earthdata Login](https://urs.earthdata.nasa.gov/); put the generated token into a `.env` file in
the repository root (never committed):

```
EARTHDATA_TOKEN=<your token>
```

```bash
uv sync                                                    # install
uv run analog freeze --profile profiles/mars-rover-jezero.json   # fix the profile version
uv run analog grid                                         # download data, build the Earth grid
uv run analog run --profile mars-rover-jezero@1.0.0        # screen, refine and rank
uv run analog site --latest                                # build the website locally
uv run analog publish --latest --allow-unvalidated         # copy it to public/ for deployment
```

The first grid build downloads about 4 GB (one reference year, `config/settings.json`); later
runs reuse cached data and stages. Settings, data sources and grid layers are configured in
`config/`.

## Current limitations

- One reference year (2023) for the Earth climatologies.
- Scores are not yet calibrated against known Earth analog sites; the website says so on every
  page.
- The profile targets plant-free terrain, so vegetated mineral analogs (for example Lake Salda)
  are excluded by design.
- Near coasts, the regional slope can include sea-floor relief from the elevation model.

## Data

NASA MODIS (MCD12C1, MOD11C3, MOD13C2), NASA POWER, NOAA ETOPO 2022, NASADEM and Copernicus
DEM GLO-30 (via Microsoft Planetary Computer), NASA EMIT; for Mars: MRO CRISM, CTX and
MOLA–HRSC elevation models (USGS), Mars Climate Database. Map outline: Natural Earth. Full
versions, licences and citations are in `config/sources.json` and on the website's
"Data & run" page.

## Repository

| What | Where |
|---|---|
| Application code | `src/analogfinder/`, tests in `tests/` |
| Configuration and Mars profile | `config/`, `profiles/` |
| Specification, plan, decisions, tasks (GitHub Spec Kit) | `specs/001-earth-analog-finder/` |
| Project rules | `.specify/memory/constitution.md` |
| Project brief (English / Ukrainian) | `BRIEF.md` |
| Background research | `solution_ideas.md`, `outputs/*.pdf` |
| Published website | `public/` (deployed by `.github/workflows/pages.yml`) |

`terramars_v2_project/` is an earlier, separate prototype and not part of the application.
