# Earth Analog Finder — agent guide

Spec-driven project managed with GitHub Spec Kit. Read these before changing anything:

- Constitution (non-negotiable rules): `.specify/memory/constitution.md`
- Feature spec: `specs/001-earth-analog-finder/spec.md`
- Plan and hand-off phases: `specs/001-earth-analog-finder/plan.md`
- Decisions (D-001…D-025): `specs/001-earth-analog-finder/research.md`
- Data model and contracts: `specs/001-earth-analog-finder/data-model.md`, `contracts/`
- Tasks (T001…T088, source of truth for issues): `specs/001-earth-analog-finder/tasks.md`

Spec Kit commands are available as `/speckit-*` skills (`.claude/skills/`). The current feature
is set in `.specify/feature.json` (machine-local; recreate it as shown in `README.md`).

Rules of thumb: weights and data sources live only in configuration, never in code; every
stage writes only into the stage-cache directory it is given; credentials never go into the
repository; `terramars_v2_project/` is a separate earlier prototype and is not touched by this
feature.
