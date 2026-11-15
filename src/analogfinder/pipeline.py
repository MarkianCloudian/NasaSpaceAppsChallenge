"""Stage orchestration, stage cache and run records (research D-011, D-023, D-025, task T054).

`run_all(profile_ref, options)` executes `check → grid → screen → refine → rank → calibrate`
for a frozen
profile (`id@version`; drafts are refused). Every stage output lives once in
`data/stages/<stage>/<stage_fp>/` (atomic, `_COMPLETE`); a complete entry is reused and logged
"reused". Stage fingerprints follow the D-011 table:

  screen  ← profile content_hash, grid_id, settings screen_min_score, max_area_km2, footprint.*
  refine  ← screen fp, dataset_version + fallback of every Earth source used by refinement
            criteria, hash of config/mineral_classes.json, settings emit.*, coverage.*,
            refine.* (after CLI overrides), site_top_n
  rank    ← refine fp (with `--skip-refine`: screen fp + "skipped")
  calibrate ← rank fp, hash of config/known_analogs.json, settings stability.* (T079)

`run_id` = fingerprint of the ordered (stage, fingerprint) list. `data/runs/<run_id>/` holds
`run_record.json` (with `stage_fingerprints`) and hard links (or copies) of the final files;
`data/runs/index.json` maps `id@version` to its run ids by date. A run whose directory is
already complete prints "reused <run_id>" and writes nothing. Stage code only receives its
output directory through `StageContext.stage_dir` and never builds paths itself.

`--skip-refine` = screening preview (D-025): no refinement, `refinement.stop = "skipped"`,
every area `screened_only` with its `upper_bound`, nothing ranked, `calibrate` skipped.

The stage functions are replaceable (`Hooks`) so tests can run the orchestration on synthetic
data; by default they are `grid.build.build_grid`, `screening.run` + `grouping.group` (T048,
T049), `refine.scheduler.schedule` (T052), `rank.rank` (T053) and `calibrate.calibrate`
(T077, T078). The `check` stage runs
`sources.check.run(ctx)` (T023) when that module exists, else it is reported as skipped.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import config, errors, stage_io, storage
from .profiles.load import load_frozen
from .types import Profile, StageContext

log = logging.getLogger("analogfinder.pipeline")

FINAL_FILES = ("results.json", "results.csv")
CALIBRATION_FILES = ("calibration.json",)
DEFAULT_HOOKS = None  # tests may set a Hooks instance used when run_all gets none
INDEX = "index.json"


@dataclass
class Options:
    config_dir: Path = Path("config")
    data_dir: Path = Path("data")
    profiles_dir: Path = Path("profiles")
    skip_refine: bool = False
    max_terrain_areas: int | None = None
    max_mineral_areas: int | None = None
    until: str = "calibrate"  # last stage to execute: screen | refine | rank | calibrate


def _missing(name: str, task: str):
    def fn(*a, **k):
        raise errors.AnalogError(f"stage needs {name} ({task}), which is not implemented yet")

    return fn


def _import(path: str, task: str):
    mod, attr = path.split(":")
    try:
        return getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError):
        return _missing(path, task)


@dataclass
class Hooks:
    """Stage functions; defaults import the real modules lazily."""

    check: Callable[[StageContext], int | None] | None = None
    grid: Callable[[StageContext], Any] | None = None  # -> GridVersion-like (grid_id, ...)
    screen: Callable[[StageContext], Any] | None = None  # -> ScreeningResult
    group: Callable[[Any, StageContext], list] | None = None  # -> list[CandidateArea]
    refine: Callable[..., tuple] | None = None  # (areas, ctx) -> (areas, summary)
    rank: Callable[..., dict] | None = None
    calibrate: Callable[..., dict] | None = None  # (results, screening, ctx, areas=...) -> dict
    sources: Callable[[Options], Any] | None = None  # -> SourceRegistry

    def resolved(self) -> Hooks:
        def grid_default(ctx):
            from .grid.build import build_grid

            return build_grid(ctx).grid

        def sources_default(opts):
            from .sources.base import SourceRegistry

            return SourceRegistry.from_config(config.load_sources(opts.config_dir), opts.data_dir)

        def check_default(ctx):
            try:
                mod = importlib.import_module("analogfinder.sources.check")
            except ImportError:
                return None  # T023 not implemented: reported as skipped
            return mod.run(ctx)

        return Hooks(
            check=self.check or check_default,
            grid=self.grid or grid_default,
            screen=self.screen or _import("analogfinder.screening:run", "T048"),
            group=self.group or _import("analogfinder.grouping:group", "T049"),
            refine=self.refine or _import("analogfinder.refine.scheduler:schedule", "T052"),
            rank=self.rank or _import("analogfinder.rank:rank", "T053"),
            calibrate=self.calibrate or _import("analogfinder.calibrate:calibrate", "T077"),
            sources=self.sources or sources_default,
        )


# --- fingerprints (research D-011) ------------------------------------------------------


def screen_fp(profile: Profile, grid_id: str, settings) -> str:
    return storage.fingerprint(
        {
            "profile": profile.content_hash,
            "grid_id": grid_id,
            "screen_min_score": settings["screen_min_score"],
            "max_area_km2": settings["max_area_km2"],
            "footprint": settings["footprint"],
        }
    )


def refine_fp(screen: str, profile: Profile, settings, sources_cfg, mineral_classes) -> str:
    entries = {e["source_id"]: e for e in sources_cfg.get("sources", [])}
    used: dict[str, dict] = {}
    for c in profile.criteria:
        if c.evaluation_scale in ("refinement", "both"):
            for sid in c.earth_sources:
                todo = [sid]
                while todo:  # the source and its fallback chain
                    s = todo.pop()
                    if s in used or s not in entries:
                        continue
                    used[s] = {
                        "dataset_version": entries[s].get("dataset_version"),
                        "fallback": entries[s].get("fallback"),
                    }
                    if entries[s].get("fallback"):
                        todo.append(entries[s]["fallback"])
    return storage.fingerprint(
        {
            "screen": screen,
            "sources": used,
            "mineral_classes": storage.fingerprint(mineral_classes),
            "emit": settings["emit"],
            "coverage": settings["coverage"],
            "refine": settings["refine"],
            "site_top_n": settings["site_top_n"],
        }
    )


def rank_fp(refine: str | None, screen: str) -> str:
    if refine is None:
        return storage.fingerprint({"screen": screen, "refine": "skipped"})
    return storage.fingerprint({"refine": refine})


def calibrate_fp(rank: str, settings, known_analogs) -> str:
    return storage.fingerprint(
        {
            "rank": rank,
            "known_analogs": storage.fingerprint(known_analogs),
            "stability": settings["stability"],
        }
    )


def run_id_of(stage_fps: list[tuple[str, str]]) -> str:
    return storage.fingerprint([list(x) for x in stage_fps])


# --- helpers ----------------------------------------------------------------------------


def _materialise(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _stage(data_dir, name: str, fp: str, work: Callable[[Path], None]) -> tuple[Path, bool, float]:
    """Reuse `data/stages/<name>/<fp>/` when complete, else build it atomically."""
    d = storage.stage_dir(data_dir, name, fp)
    t0 = time.monotonic()
    if storage.is_complete(d):
        log.info("%s: reused (%s)", name, fp)
        return d, True, 0.0
    if d.exists():  # renamed but _COMPLETE never written: set it aside, never trust it
        d.rename(d.with_name(f"{d.name}.partial-stale-{int(time.time())}"))
    with storage.atomic_dir(d, manifest={"stage": name, "fingerprint": fp}) as tmp:
        work(tmp)
    secs = round(time.monotonic() - t0, 3)
    log.info("%s: computed (%s, %.1f s)", name, fp, secs)
    return d, False, secs


def _write_index(data_dir: Path, ref: str, run_id: str) -> None:
    path = Path(data_dir) / "runs" / INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    index = stage_io.read_json(path) if path.exists() else {}
    runs = index.setdefault(ref, [])
    if all(r["run_id"] != run_id for r in runs):
        runs.append(
            {"run_id": run_id, "date": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
        )
    tmp = path.with_name(f"{INDEX}.partial-{os.getpid()}")
    stage_io.write_json(tmp, index)
    os.replace(tmp, path)


def resolve_ref(
    data_dir, profile: str | None = None, run: str | None = None, latest: bool = False
) -> str:
    """`--profile ID@VER` | `--run RUN_ID` | `--latest` -> profile reference."""
    if profile:
        return profile
    index_path = Path(data_dir) / "runs" / INDEX
    index = stage_io.read_json(index_path) if index_path.exists() else {}
    if run:
        rec = Path(data_dir) / "runs" / run / "run_record.json"
        if not rec.exists():
            raise errors.ValidationError(f"run {run} not found")
        p = stage_io.read_json(rec)["profile"]
        return f"{p['id']}@{p['version']}"
    if latest:
        best = max(((r["date"], ref) for ref, runs in index.items() for r in runs), default=None)
        if best is None:
            raise errors.ValidationError("no runs yet: use --profile ID@VER")
        return best[1]
    raise errors.ValidationError("give --profile ID@VER, --run RUN_ID or --latest")


# --- the run ----------------------------------------------------------------------------


@dataclass
class RunResult:
    run_id: str
    reused: bool
    stages: list[dict] = field(default_factory=list)
    results: dict | None = None
    exit_code: int = errors.OK
    calibration: dict | None = None


def run_all(profile_ref: str, options: Options, hooks: Hooks | None = None) -> RunResult:
    h = (hooks or DEFAULT_HOOKS or Hooks()).resolved()
    data_dir = Path(options.data_dir)
    profile = load_frozen(profile_ref, options.profiles_dir)  # refuses drafts
    settings = dict(config.load_settings(options.config_dir))
    refine_cfg = dict(settings["refine"])
    if options.max_terrain_areas is not None:
        refine_cfg["max_terrain_areas"] = options.max_terrain_areas
    if options.max_mineral_areas is not None:
        refine_cfg["max_mineral_areas"] = options.max_mineral_areas
    settings["refine"] = refine_cfg
    sources_cfg = config.load_sources(options.config_dir)
    started = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    ctx = StageContext(
        stage="check",
        stage_dir=data_dir,
        data_dir=data_dir,
        config_dir=Path(options.config_dir),
        settings=settings,
        profile=profile,
        grid=None,
        sources=h.sources(options),
        log=log,
    )
    stages: list[dict] = []

    code = h.check(ctx)
    if code is None:
        log.info("check: skipped (sources/check.py, T023, not implemented yet)")
    elif code == errors.SOURCE_CHECK_FAILED:
        raise errors.SourceCheckError("pre-run source check failed (see table above)")

    t0 = time.monotonic()
    grid = h.grid(replace(ctx, stage="grid"))
    ctx = replace(ctx, grid=grid)
    stages.append(
        {
            "name": "grid",
            "status": "complete",
            "seconds": round(time.monotonic() - t0, 3),
            "fingerprint": grid.grid_id,
        }
    )
    log.info("grid: %s", grid.grid_id)

    sfp = screen_fp(profile, grid.grid_id, settings)
    fps: list[tuple[str, str]] = [("grid", grid.grid_id), ("screen", sfp)]

    def do_screen(tmp: Path) -> None:
        sctx = replace(ctx, stage="screen", stage_dir=tmp)
        scr = h.screen(sctx)
        areas = h.group(scr, sctx)
        stage_io.save_screening(tmp, scr)
        stage_io.save_areas(tmp / "areas.json", areas)

    sdir, reused, secs = _stage(data_dir, "screen", sfp, do_screen)
    stages.append(
        {
            "name": "screen",
            "status": "reused" if reused else "complete",
            "seconds": secs,
            "fingerprint": sfp,
        }
    )
    if options.until == "screen":
        return _finish(profile_ref, profile, data_dir, fps, stages, None, started)

    rfp = None
    if options.skip_refine:
        refine_dir = None
        stages.append({"name": "refine", "status": "skipped", "fingerprint": sfp})
    else:
        rfp = refine_fp(
            sfp, profile, settings, sources_cfg, config.load_mineral_classes(options.config_dir)
        )
        fps.append(("refine", rfp))

        def do_refine(tmp: Path) -> None:
            rctx = replace(ctx, stage="refine", stage_dir=tmp)
            areas, summary = h.refine(stage_io.load_areas(sdir / "areas.json"), rctx)
            stage_io.save_areas(tmp / "areas.json", areas)
            stage_io.write_json(tmp / "refinement.json", summary)

        refine_dir, reused, secs = _stage(data_dir, "refine", rfp, do_refine)
        stages.append(
            {
                "name": "refine",
                "status": "reused" if reused else "complete",
                "seconds": secs,
                "fingerprint": rfp,
            }
        )
        if options.until == "refine":
            return _finish(profile_ref, profile, data_dir, fps, stages, None, started)

    kfp = rank_fp(rfp, sfp)
    fps.append(("rank", kfp))
    cfp = None
    if refine_dir is not None and options.until == "calibrate":  # preview: skipped (D-025)
        cfp = calibrate_fp(kfp, settings, config.load_known_analogs(options.config_dir))
        fps.append(("calibrate", cfp))
    run_id = run_id_of(fps)
    if storage.is_complete(storage.run_dir(data_dir, run_id)):
        log.info("reused %s", run_id)
        rdir = storage.run_dir(data_dir, run_id)
        res = stage_io.read_json(rdir / "results.json")
        cal = rdir / CALIBRATION_FILES[0]
        cal = stage_io.read_json(cal) if cal.exists() else None
        return RunResult(run_id, True, stages, res, _exit(res), cal)

    def do_rank(tmp: Path) -> None:
        kctx = replace(ctx, stage="rank", stage_dir=tmp)
        screening = stage_io.load_screening(sdir)
        if refine_dir is None:  # screening preview (D-025): bounds only, nothing refined
            from .refine.scheduler import initial_bounds

            areas = stage_io.load_areas(sdir / "areas.json")
            if any(a.upper_bound is None for a in areas):
                initial_bounds([a for a in areas if a.upper_bound is None], kctx)
            summary = {"stop": "skipped", "proven_top": 0, "terrain_areas": 0, "mineral_areas": 0}
        else:
            areas = stage_io.load_areas(refine_dir / "areas.json")
            summary = stage_io.read_json(refine_dir / "refinement.json")
        h.rank(
            areas,
            screening,
            kctx,
            refinement=summary,
            stages=stages + [{"name": "rank", "status": "complete", "fingerprint": kfp}],
            stage_fingerprints=dict(fps),
            started_at=started,
            sources_config=sources_cfg,
            run_id=run_id,
        )

    kdir, reused, secs = _stage(data_dir, "rank", kfp, do_rank)
    stages.append(
        {
            "name": "rank",
            "status": "reused" if reused else "complete",
            "seconds": secs,
            "fingerprint": kfp,
        }
    )
    if cfp is None:
        if refine_dir is None:
            stages.append({"name": "calibrate", "status": "skipped", "fingerprint": kfp})
        return _finish(profile_ref, profile, data_dir, fps, stages, kdir, started)

    def do_calibrate(tmp: Path) -> None:
        cctx = replace(ctx, stage="calibrate", stage_dir=tmp)
        h.calibrate(
            stage_io.read_json(kdir / "results.json"),
            stage_io.load_screening(sdir),
            cctx,
            areas=stage_io.load_areas(refine_dir / "areas.json"),
        )

    cdir, reused, secs = _stage(data_dir, "calibrate", cfp, do_calibrate)
    stages.append(
        {
            "name": "calibrate",
            "status": "reused" if reused else "complete",
            "seconds": secs,
            "fingerprint": cfp,
        }
    )
    return _finish(profile_ref, profile, data_dir, fps, stages, kdir, started, cdir)


def _exit(results: dict | None) -> int:
    if results is None:
        return errors.OK
    from .rank import exit_code

    return exit_code(results)


def _finish(ref, profile, data_dir, fps, stages, kdir, started, cdir=None) -> RunResult:
    run_id = run_id_of(fps)
    rdir = storage.run_dir(data_dir, run_id)
    results = stage_io.read_json(kdir / "results.json") if kdir else None
    cal = cdir / CALIBRATION_FILES[0] if cdir else None
    calibration = stage_io.read_json(cal) if cal is not None and cal.exists() else None
    if storage.is_complete(rdir):
        log.info("reused %s", run_id)
        return RunResult(run_id, True, stages, results, _exit(results), calibration)
    if rdir.exists():
        rdir.rename(rdir.with_name(f"{rdir.name}.partial-stale-{int(time.time())}"))
    if results is not None:
        record = dict(results["run_record"])
    else:  # a partial run (`screen` / `refine` alone): record of the stages only
        record = {
            "profile": {
                "id": profile.profile_id,
                "version": profile.version,
                "content_hash": profile.content_hash,
            },
            "grid_id": dict(fps)["grid"],
            "started_at": started,
        }
    record.update(
        {
            "run_id": run_id,
            "stages": stages,
            "stage_fingerprints": dict(fps),
            "finished_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
    )
    with storage.atomic_dir(rdir, manifest={"run_id": run_id}) as tmp:
        stage_io.write_json(tmp / "run_record.json", record)
        for name in FINAL_FILES if kdir else ():
            if (kdir / name).exists():
                _materialise(kdir / name, tmp / name)
        for name in CALIBRATION_FILES if cdir else ():
            if (cdir / name).exists():
                _materialise(cdir / name, tmp / name)
    _write_index(data_dir, ref, run_id)
    log.info("run: %s", run_id)
    return RunResult(run_id, False, stages, results, _exit(results), calibration)


def run_stage(name: str, ctx: StageContext) -> Path:  # contract signature (internal-api.md)
    """Run the pipeline up to `name` for ctx.profile and return that stage's directory."""
    opts = Options(config_dir=ctx.config_dir, data_dir=ctx.data_dir, until=name)
    res = run_all(ctx.profile.ref, opts)
    return storage.stage_dir(
        ctx.data_dir, name, dict((s["name"], s["fingerprint"]) for s in res.stages)[name]
    )


def print_summary(res: RunResult, out=None) -> None:
    out = out or __import__("sys").stdout
    if res.reused:
        print(f"reused {res.run_id}", file=out)
    else:
        print(f"run: {res.run_id}", file=out)
    if res.results is not None:
        ranked = [c for c in res.results["candidates"] if c["status"] == "ranked"]
        print(
            json.dumps({"ranked": len(ranked), "top": [c["area_id"] for c in ranked[:5]]}), file=out
        )
    if res.calibration is not None:
        cal = res.calibration
        print(
            json.dumps(
                {
                    "calibration": {
                        "flag_for_review": cal["flag_for_review"],
                        "flag_reasons": cal["flag_reasons"],
                        "known_sites": {s["site_id"]: s["rank"] for s in cal["known_sites"]},
                    }
                }
            ),
            file=out,
        )
