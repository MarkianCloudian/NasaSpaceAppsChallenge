"""`analog` command line (contracts/cli.md). Sub-commands are wired as their tasks land."""

from __future__ import annotations

import argparse
import sys
import traceback

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


HANDLERS = {"validate": _validate, "freeze": _freeze}  # command name -> callable(args) -> int


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
