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
| Tasks T001–T089 | `specs/001-earth-analog-finder/tasks.md` |
| Project brief (English / Ukrainian) | `BRIEF.md` |
| Background: solution ideas, dataset access report, analog methods | `solution_ideas.md`, `outputs/*.pdf` (LaTeX sources `outputs/*.tex`) |
| Early profile drafts | `sample*.json` (`sample-edited.json` seeds the Mars profile) |

`terramars_v2_project/` is an earlier, separate prototype.

### Working with Spec Kit

1. Optional CLI: `uv tool install specify-cli` (Python ≥ 3.11 via uv) — the `/speckit-*`
   commands in Claude Code work without it.
2. The active feature is already set in `.specify/feature.json` (committed).
3. In Claude Code, run commands from the repository root and always name the task, e.g.
   `/speckit-implement only T037`.

### Contributing a task

Follow **`CLAUDE.md` → *Working on a task*** (applies to people and AI agents): one task = one
issue = one PR into `dev-app-v1` with `Closes #<issue>` (any branch name; small manual fixes may
go straight to `dev-app-v1`). Check that the issue's "Depends on" issues are closed first. Shared Python types and module signatures are fixed in
`specs/001-earth-analog-finder/contracts/internal-api.md`. Do not tick checkboxes in `tasks.md`
in feature PRs; the closed issue is the status. Without a local AI agent you can comment
`@claude implement this issue following CLAUDE.md; open a PR into dev-app-v1.` on the issue.
