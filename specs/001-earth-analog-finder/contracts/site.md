# Site Contract: generated static results site

Output of `analog site --run RUN_ID` → `data/runs/<run_id>/site/`; `analog publish` copies it to
`public/`, which is committed and deployed by `.github/workflows/pages.yml` (GitHub Pages) or
served by Cloudflare Pages with output directory `public` and no build command (research D-022). Static files only; no server, no live requests.

## Files

```text
index.html                 # map + ranked table for the default profile
p/<profile_id>/index.html  # same, per profile (v1: one)
p/<profile_id>/c/<area_id>.html   # one page per candidate
method.html                # how scores are computed (plain language) + profile & weights
about.html                 # data sources, citations, run record summary, calibration
assets/style.css           # single stylesheet, system font stack
assets/map.js              # optional, vanilla, < 10 KB, non-essential
```

## Required content

- **All pages**: when the run was published with `--allow-unvalidated`, a banner "Not validated
  against known analogs" with the calibration `flag_reasons` at the top of every page (D-018).
- **All pages (preview)**: run without refinement → banner "Screening preview — not ranked";
  table lists screened areas by screening score with upper bound, no ranks (D-025).
- **Index and about page**: refinement status — "top N proven complete" (`bound_reached`) or
  "top results not proven complete: refinement cap reached (k of N proven)" (`cap_reached`).
- **Index**: inline SVG world map (land outline + one circle per candidate, linked to its page;
  new vs known styled differently when dedup ran) and an HTML `<table>` of ranked candidates
  (rank, name/coords, overall score, confidence, limiting criterion, label). Banner when profile
  has placeholder values; message when there are zero candidates; note "deduplication not
  applied" when relevant.
- **Candidate page**: coordinates, area size, overall score, confidence, limiting criterion,
  known/new label (+ matched site), per-criterion table with columns: criterion, category, Earth
  value + unit, target, deviation (unit), deviation / tolerance, score, comparison mode
  (absolute / relative / not comparable), data source; analogy-limits list; small regional SVG
  inset (optional).
- **Method page**: screening → veto → per-criterion score → weighted geometric mean →
  confidence, in ≤ 300 words, plus the profile's criteria, targets and weights.
- **About page**: every data source with version, licence, citation; every grid layer with its
  source, reference period, resampling and baseline; run id, profile id@version, grid id, dates;
  calibration summary (known-site ranks, stability). All taken from `site_inputs.json` (research
  D-023), never from live configuration.

## Constraints (tested in `tests/site/`)

| Rule | Test |
|---|---|
| Initial download of `index.html` + CSS + SVG + JS < 2 MB | sum file sizes |
| No external requests | no `http(s)://` in `src`/`href` of script, link, img, font; no `@import url(http…)`; no `@font-face` |
| Readable without scripting | all FR-036 fields present in HTML source; links work |
| Script optional | pages pass content test with `map.js` deleted |
| Valid relative links | every internal link resolves to a file |
| Different profiles not mixed | each table contains one profile only |
| Rendered from snapshot | method page shows weights and `percentile_population` and about page shows each layer's period and licence, all present in `site_inputs.json`; changing `config/sources.json` after the build does not change a rebuilt old run |
| Unvalidated banner | site built from a flagged calibration with override shows the banner on every page; without override `publish` exits 8 |
