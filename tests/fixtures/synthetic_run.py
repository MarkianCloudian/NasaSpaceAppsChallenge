"""Pipeline hooks for an offline run on the synthetic grid (real screening, grouping, scheduler
and rank; fake terrain/EMIT sources)."""

from __future__ import annotations

from analogfinder import pipeline
from analogfinder.refine import scheduler
from analogfinder.types import GroupResult
from tests.fixtures.synthetic import build_synthetic_grid


def terrain_fn(area, ctx):
    return GroupResult("terrain", {"traverse_slope": 6.0, "roughness": 2.0}, "nasadem-pc", 1.0)


def mineral_fn(area, ctx):
    return GroupResult(
        "mineral",
        {
            "mineral_class_fractions": {"fe_mg_smectite": 0.1, "carbonate": 0.04},
            "aqueous_mineral_present": True,
        },
        "emit-l2b-min",
        0.9,
    )


def synthetic_hooks(fail_refine: list | None = None) -> pipeline.Hooks:
    grid = build_synthetic_grid().as_grid_version()

    def refine(areas, ctx):
        if fail_refine:
            fail_refine.pop()
            raise RuntimeError("simulated failure during refine")
        return scheduler.schedule(areas, ctx, terrain_fn, mineral_fn, lambda fp, c: True)

    return pipeline.Hooks(
        check=lambda ctx: None, grid=lambda ctx: grid, refine=refine, sources=lambda opts: None
    )
