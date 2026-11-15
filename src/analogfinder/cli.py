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
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p


def _not_implemented(args) -> int:
    print(f"analog {args.command}: not implemented yet", file=sys.stderr)
    return errors.UNEXPECTED


HANDLERS = {}  # command name -> callable(args) -> int, filled as stages are implemented


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
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
