"""`analog` command line (contracts/cli.md). Sub-commands are wired as their tasks land."""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from . import errors

COMMANDS = {
    "validate": "validate config files and/or a profile",
    "freeze": "compute weights and freeze a profile version",
    "extract": "propose profile targets from planetary data",
    "check": "pre-run source check",
    "grid": "build the global Earth grid",
    "screen": "screen the grid against a profile",
    "refine": "refine candidate areas (fine terrain, EMIT mineralogy)",
    "rank": "final scoring and ranking",
    "calibrate": "score known analog sites and weight stability",
    "dedup": "label known analogs vs new candidates",
    "site": "build the static results site",
    "publish": "copy a site into public/",
    "run": "run all stages",
    "clean": "remove old grids, runs and partial directories",
    "status": "show grid/run/cache status",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="analog", description="Earth Analog Finder")
    p.add_argument("--config-dir", default="config/")
    p.add_argument("--data-dir", default="data/")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_ in COMMANDS.items():
        sub.add_parser(name, help=help_, add_help=False)  # command options parsed by its handler
    return p


def _not_implemented(args) -> int:
    print(f"analog {args.command}: not implemented yet", file=sys.stderr)
    return errors.UNEXPECTED


def _validate(args) -> int:
    """`analog validate --profile FILE [--profiles-dir DIR]` and/or `analog validate --config`."""
    import json

    from . import config
    from .profiles.validate import load_validation_config, summary, validate

    p = argparse.ArgumentParser(prog="analog validate")
    p.add_argument("--profile")
    p.add_argument("--config", action="store_true")
    p.add_argument("--profiles-dir", default="profiles")
    opts = p.parse_args(args.rest)
    if not opts.profile and not opts.config:
        p.print_usage(sys.stderr)
        return errors.USAGE
    problems: list[str] = []
    if opts.config:
        loaders = (
            config.load_settings,
            config.load_sources,
            config.load_purposes,
            config.load_known_analogs,
            config.load_layers,
            config.load_mineral_classes,
        )
        for load in loaders:
            try:
                load(args.config_dir)
            except errors.ConfigError as e:
                problems.append(str(e))
        if not problems:
            print("config OK")
    if opts.profile:
        try:
            draft = json.loads(open(opts.profile, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError) as e:
            raise errors.ValidationError(f"{opts.profile}: {e}") from e
        cfg = load_validation_config(args.config_dir, opts.profiles_dir)
        found = validate(draft, cfg)
        problems += found
        if not found:
            s = summary(draft)
            print(
                f"{s['profile_id']}@{s['version']}: OK — scored {s['scored']}, veto {s['veto']}, "
                f"normalized {s['normalized']}, not comparable {s['not_comparable']}"
            )
    for msg in problems:
        print(msg, file=sys.stderr)
    return errors.VALIDATION_FAILED if problems else errors.OK


def _freeze(args) -> int:
    """`analog freeze --profile FILE [--profiles-dir DIR]`."""
    from .profiles.freeze import freeze

    p = argparse.ArgumentParser(prog="analog freeze")
    p.add_argument("--profile", required=True)
    p.add_argument("--profiles-dir", default="profiles")
    opts = p.parse_args(args.rest)
    path, status = freeze(opts.profile, args.config_dir, opts.profiles_dir)
    print(f"{path}: unchanged, reused" if status == "reused" else f"{path}: frozen")
    return errors.OK


def _grid(args) -> int:
    """`analog grid`: build or reuse the global grid version."""
    import json
    import logging

    from . import config
    from .grid.build import build_grid
    from .sources.base import SourceRegistry
    from .types import StageContext

    p = argparse.ArgumentParser(prog="analog grid")
    p.parse_args(args.rest)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO,
        stream=sys.stderr,
    )
    settings = config.load_settings(args.config_dir)
    sources = SourceRegistry.from_config(config.load_sources(args.config_dir), args.data_dir)
    ctx = StageContext(
        stage="grid",
        stage_dir=Path(args.data_dir),
        data_dir=Path(args.data_dir),
        config_dir=Path(args.config_dir),
        settings=settings,
        profile=None,
        grid=None,
        sources=sources,
        log=logging.getLogger("analogfinder.grid"),
    )
    result = build_grid(ctx)
    m = result.grid.manifest
    missing = [x["layer_id"] for x in m.get("missing_layers", [])]
    if args.json:
        print(
            json.dumps(
                {
                    "grid_id": result.grid.grid_id,
                    "reused": result.reused,
                    "status": m["status"],
                    "missing_layers": missing,
                }
            )
        )
    else:
        verb = "reused" if result.reused else "built"
        print(f"{verb} {result.grid.grid_id}")
        if missing:
            print(f"partial: missing layers {', '.join(missing)}", file=sys.stderr)
    return errors.PARTIAL_RESULT if m["status"] == "partial" else errors.OK


def _status(args) -> int:
    """`analog status`: grid versions, runs and stage-cache entries with completeness."""
    import json

    from .grid.build import status_report

    rep = status_report(args.data_dir)
    if args.json:
        print(json.dumps(rep, indent=1))
        return errors.OK
    print(f"grids ({len(rep['grids'])}):")
    for g in rep["grids"]:
        extra = f" missing: {', '.join(g['missing_layers'])}" if g["missing_layers"] else ""
        state = g["status"] if g["complete"] else "INCOMPLETE"
        print(f"  {g['grid_id']}  {state}  {g['layers']} layers{extra}")
    print(f"runs ({len(rep['runs'])}):")
    for r in rep["runs"]:
        print(f"  {r['run_id']}  {'complete' if r['complete'] else 'INCOMPLETE'}")
    print(f"stage cache ({len(rep['stages'])}):")
    for s in rep["stages"]:
        print(f"  {s['stage']}/{s['fingerprint']}  {'complete' if s['complete'] else 'INCOMPLETE'}")
    return errors.OK


def _extract(args) -> int:
    """`analog extract --profile FILE [--criteria ID,...]`: print target proposals (T074)."""
    import json

    from . import config
    from .planetary.extract import load_profile, propose

    p = argparse.ArgumentParser(prog="analog extract")
    p.add_argument("--profile", required=True)
    p.add_argument("--criteria", default=None, help="comma-separated criterion ids")
    p.add_argument("--min-class-fraction", type=float, default=0.001)
    p.add_argument("--max-crism-obs", type=int, default=3)
    opts = p.parse_args(args.rest)
    crit = [c.strip() for c in opts.criteria.split(",")] if opts.criteria else None
    rows = propose(
        load_profile(opts.profile),
        config.load_sources(args.config_dir),
        config.load_mineral_classes(args.config_dir),
        criteria=crit,
        data_dir=args.data_dir,
        min_class_fraction=opts.min_class_fraction,
        max_crism_obs=opts.max_crism_obs,
    )
    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return errors.OK
    for r in rows:
        print(f"== {r['criterion']}")
        if "error" in r:
            print(f"   not available: {r['error']}")
            continue
        print(f"   measured: {json.dumps(r['measured'], ensure_ascii=False)}")
        print(f"   current target: {json.dumps(r['current_target'], ensure_ascii=False)}")
        print("   proposed (paste into the criterion):")
        print(
            "   " + json.dumps(r["proposed"], indent=1, ensure_ascii=False).replace("\n", "\n   ")
        )
    return errors.OK


def _pipeline(args, until: str) -> int:
    """`analog run|screen|refine|rank|calibrate|dedup` (contracts/cli.md, D-011/D-023/D-025).

    `run` also renders the site into `data/runs/<run_id>/site/` (T066)."""
    import logging

    from .pipeline import Options, print_summary, resolve_ref, run_all

    p = argparse.ArgumentParser(prog=f"analog {args.command}")
    p.add_argument("--profile", help="frozen profile ID@VER")
    p.add_argument("--run", dest="run_id", help="base run id")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--profiles-dir", default="profiles")
    if args.command in ("run", "refine"):
        p.add_argument("--max-terrain-areas", type=int)
        p.add_argument("--max-mineral-areas", type=int)
    if args.command == "run":
        p.add_argument("--skip-refine", action="store_true")
        p.add_argument("--no-dedup", action="store_true")
    opts = p.parse_args(args.rest)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO,
        stream=sys.stderr,
        format="%(message)s",
    )
    ref = resolve_ref(args.data_dir, opts.profile, opts.run_id, opts.latest)
    res = run_all(
        ref,
        Options(
            config_dir=Path(args.config_dir),
            data_dir=Path(args.data_dir),
            profiles_dir=Path(opts.profiles_dir),
            skip_refine=getattr(opts, "skip_refine", False),
            max_terrain_areas=getattr(opts, "max_terrain_areas", None),
            max_mineral_areas=getattr(opts, "max_mineral_areas", None),
            until=until,
            no_dedup=getattr(opts, "no_dedup", False),
        ),
    )
    print_summary(res)
    return res.exit_code


def _site(args) -> int:
    """`analog site --run RUN_ID | --latest` and `analog publish ... [--allow-unvalidated]`."""
    import logging

    from . import config
    from .site import build

    p = argparse.ArgumentParser(prog=f"analog {args.command}")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", dest="run_id")
    g.add_argument("--latest", action="store_true")
    p.add_argument("--profiles-dir", default="profiles")
    if args.command == "publish":
        p.add_argument("--allow-unvalidated", action="store_true")
        p.add_argument("--public-dir", default=None, help="default: settings paths.public")
    opts = p.parse_args(args.rest)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO,
        stream=sys.stderr,
        format="%(message)s",
    )
    run_id = opts.run_id or build.latest_run_id(args.data_dir)
    if args.command == "publish":
        public = opts.public_dir or config.load_settings(args.config_dir)["paths"]["public"]
        return build.publish(
            args.data_dir,
            args.config_dir,
            opts.profiles_dir,
            run_id,
            public,
            allow_unvalidated=opts.allow_unvalidated,
        )
    path, reused = build.build_site(args.data_dir, args.config_dir, opts.profiles_dir, run_id)
    print(f"{'reused' if reused else 'built'} site of run {run_id}: {path}")
    return errors.OK


HANDLERS = {
    "site": _site,
    "publish": _site,
    "run": lambda a: _pipeline(a, "site"),
    "screen": lambda a: _pipeline(a, "screen"),
    "refine": lambda a: _pipeline(a, "refine"),
    "rank": lambda a: _pipeline(a, "rank"),
    "calibrate": lambda a: _pipeline(a, "calibrate"),
    "dedup": lambda a: _pipeline(a, "dedup"),
    "extract": _extract,
    "validate": _validate,
    "freeze": _freeze,
    "grid": _grid,
    "status": _status,
}  # command name -> callable(args) -> int


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args, rest = parser.parse_known_args(argv)
        args.rest = rest
    except SystemExit as e:  # argparse exits 0 for --help, 2 for usage errors
        return int(e.code or 0)
    if not args.command:
        parser.print_help()
        return errors.USAGE
    try:
        return HANDLERS.get(args.command, _not_implemented)(args)
    except errors.AnalogError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
    except Exception:  # noqa: BLE001
        if args.verbose:
            traceback.print_exc()
        else:
            print("unexpected error (use --verbose for a traceback)", file=sys.stderr)
        return errors.UNEXPECTED
