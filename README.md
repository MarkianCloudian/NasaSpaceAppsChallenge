# NasaSpaceAppsChallenge
Solution and sources for NASA Space Apps Challenge 2026

## Earth Analog Finder (branch `dev-app-v1`)

Spec-driven design for a tool that finds places on Earth resembling a chosen Mars (later Moon)
location for a given mission purpose, by comparing Earth datasets with frozen reference
profiles, and publishes the results as a lightweight static map site. This branch contains the
specification, plan and task list only — no application code yet.

| What | Where |
|---|---|
| Constitution (project rules) | `.specify/memory/constitution.md` |
| Specification | `specs/001-earth-analog-finder/spec.md` |
| Implementation plan (phases for hand-off) | `specs/001-earth-analog-finder/plan.md` |
| Research decisions | `specs/001-earth-analog-finder/research.md` |
| Data model, contracts (CLI, site, JSON Schemas) | `specs/001-earth-analog-finder/data-model.md`, `contracts/` |
| Validation guide | `specs/001-earth-analog-finder/quickstart.md` |
| Tasks T001–T088 | `specs/001-earth-analog-finder/tasks.md` |
| Background: solution ideas, dataset access report, analog methods | `solution_ideas.md`, `outputs/*.pdf` (LaTeX sources `outputs/*.tex`) |
| Early profile drafts | `sample*.json` (`sample-edited.json` seeds the Mars profile) |

`terramars_v2_project/` is an earlier, separate prototype.

### Working with Spec Kit

1. Install the CLI: `uv tool install specify-cli` (Python ≥ 3.11 via uv).
2. Point Spec Kit at the feature (machine-local file, not committed):
   `echo '{"feature_directory": "specs/001-earth-analog-finder"}' > .specify/feature.json`
3. In Claude Code, the `/speckit-*` commands (`.claude/skills/`) work from the repository root,
   e.g. `/speckit-analyze`, `/speckit-implement`.
