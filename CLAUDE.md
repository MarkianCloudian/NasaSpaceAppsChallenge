# Earth Analog Finder — guide for people and AI agents

Spec-driven project (GitHub Spec Kit). Development branch: `dev-app-v1`.
`terramars_v2_project/` is a separate earlier prototype — do not modify it.

## Sources of truth (read before changing anything)

| What | Where |
|---|---|
| Non-negotiable rules | `.specify/memory/constitution.md` |
| Requirements | `specs/001-earth-analog-finder/spec.md` |
| Plan, hand-off phases (A1…I2) | `specs/001-earth-analog-finder/plan.md` |
| Decisions D-001…D-026 | `specs/001-earth-analog-finder/research.md` |
| Data shapes | `specs/001-earth-analog-finder/data-model.md`, `contracts/*.schema.json` |
| CLI and site behaviour | `contracts/cli.md`, `contracts/site.md` |
| **Shared Python types and module signatures** | `contracts/internal-api.md` → `src/analogfinder/types.py` |
| Tasks T001…T089 | `specs/001-earth-analog-finder/tasks.md` |
| End-to-end checks | `specs/001-earth-analog-finder/quickstart.md` |

## Working on a task (mandatory for humans and agents)

1. **One task = one GitHub issue = one pull request into `dev-app-v1`.** Any branch name works
   (the GitHub `@claude` workflow names its own `claude/issue-N-…`; locally e.g. `task/T037-…`);
   the PR must target **`dev-app-v1`** and contain `Closes #<issue>`. Hackathon shortcut: small
   manual config or documentation fixes may be pushed directly to `dev-app-v1` (pull first).
2. **Read first**: the constitution, the task line in `tasks.md`, the plan sub-phase it names
   ("plan C2"), every research decision it names ("D-024"), and every contract or schema it
   names. For any code task also read `contracts/internal-api.md`.
3. **Check dependencies (the person starting the task)**: before starting work or tagging
   `@claude`, check on the issue or board that its "Depends on" issues are closed. Claude running
   on GitHub cannot check issue states, so it relies on this.
4. **Implement only this task.** No extra features, refactors of other modules, or new
   dependencies beyond `pyproject.toml` unless the task says so.
5. **Use the contracts as written.** Import shared types from `analogfinder.types`; follow the
   module signatures in `contracts/internal-api.md`, the JSON Schemas and `contracts/cli.md`.
   If a contract seems wrong or insufficient, comment on the issue and propose the change — do
   not silently diverge. Contract changes are edited in the contract file in the same PR.
6. **Never invent data facts.** No made-up URLs, dataset versions, thresholds, file sizes or
   scientific values. Items marked **verify** in the docs must be checked against provider
   documentation and recorded in `research.md` (*Verification results*); if you cannot verify,
   leave it marked and say so in the PR.
7. **Configuration, not code**: weights, thresholds, sources, layers and profiles live in
   `config/` and `profiles/`; never hard-code them.
8. **Stages write only into the directory they are given** (`StageContext.stage_dir`).
9. **Before finishing**: `uv run ruff format`, `uv run ruff check .`, `uv run pytest` (online
   tests are skipped by default); all must pass. Meet every "Done:" check of the task.
10. **Do not tick checkboxes in `tasks.md`** in feature PRs — the closed issue is the status; a
    maintainer ticks `tasks.md` in batches. When in doubt, ask on the issue instead of guessing.

Credentials (NASA Earthdata `~/.netrc`, Copernicus `~/.cdsapirc`) never go into the repository.

## Code conventions

Python 3.11, `from __future__ import annotations`, full type hints, frozen dataclasses for
records, numpy arrays aligned to `LandIndex` for per-cell data, `logging.getLogger("analogfinder.<module>")`,
errors from `analogfinder.errors`. Line length 100 (ruff).

## Spec Kit commands

`/speckit-*` skills are in `.claude/skills/`; the active feature is set in `.specify/feature.json`
(committed). To implement a task with Spec Kit, always name it:
`/speckit-implement only T037 — follow CLAUDE.md, do not touch other tasks`.
Never run `/speckit-implement` without a task id: it would work through every open task.

## Delegating a task to `@claude` on GitHub

1. Check that the issue's "Depends on" issues are closed.
2. Comment on the task issue:
   `@claude implement this issue following CLAUDE.md and the "Read first" list; open a PR into dev-app-v1.`
3. Claude works from `dev-app-v1` (it may run `uv`, `ruff`, `pytest`, `git`), pushes a branch
   `claude/issue-N-…` and comments a "Create PR" link.
4. Open the PR, make sure the base is `dev-app-v1` and the description has `Closes #N`, merge.
5. To answer a question from Claude, comment `@claude …` again on the same issue.
