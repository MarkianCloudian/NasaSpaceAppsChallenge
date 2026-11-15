"""Performance measurements for T087 (SC-001, SC-002, SC-003, footprint pass of T046).

Usage:
  uv run python scripts/benchmark_perf.py footprint [--radius-km 20] [--band 30:40] [--land 0.3]
  uv run python scripts/benchmark_perf.py grid [--data-dir data] [--config-dir config]
  uv run python scripts/benchmark_perf.py disk [--data-dir data]

* `footprint`: times every footprint statistic on a synthetic land mask (random blobs, fixed seed)
  restricted to a latitude band and extrapolates to the full globe by land-cell count. The band
  result is measured; the global figure is an estimate and is labelled as such.
* `grid`: times `build_grid` against real cached inputs in `--data-dir` (needs the downloaded
  sources; it reports a clear error when they are absent) and the peak RSS of this process.
* `disk`: size of `--data-dir` (SC-003, < 10 GB).
"""

from __future__ import annotations

import argparse
import logging
import resource
import sys
import time
from pathlib import Path

import numpy as np

from analogfinder import footprint
from analogfinder.types import LandIndex

N_ROWS, N_COLS, CELL = 3600, 7200, 0.05


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KiB


def synthetic_land(band: tuple[float, float], fraction: float, seed: int = 0) -> LandIndex:
    rng = np.random.default_rng(seed)
    r0 = int((90 - band[1]) / CELL)
    r1 = int((90 - band[0]) / CELL)
    noise = rng.random((N_ROWS, N_COLS)) < fraction
    # smooth into blobs so neighbourhoods are realistic (mostly land or mostly sea)
    k = np.ones(25) / 25
    noise = noise.astype("float32")
    for ax in (0, 1):
        noise = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), ax, noise)
    mask = np.zeros((N_ROWS, N_COLS), dtype=bool)
    thr = np.quantile(noise[r0:r1], 1 - fraction)
    mask[r0:r1] = noise[r0:r1] >= thr
    rows, cols = np.nonzero(mask)
    lat = 90 - (rows + 0.5) * CELL
    lon = -180 + (cols + 0.5) * CELL
    return LandIndex(
        rows=rows.astype("int32"),
        cols=cols.astype("int32"),
        lat=lat,
        lon=lon,
        area_km2=np.ones(rows.size),
    )


def bench_footprint(args) -> int:
    lo, hi = (float(x) for x in args.band.split(":"))
    land = synthetic_land((lo, hi), args.land)
    n = land.rows.size
    rng = np.random.default_rng(1)
    vals = rng.random(n).astype("float32")
    # global land cells ~ 29 % of the grid (order of magnitude; only used to extrapolate)
    global_land = int(0.29 * N_ROWS * N_COLS)
    print(f"band {lo}..{hi}°N, {n} land cells, radius {args.radius_km} km")
    print(f"{'statistic':<14}{'seconds':>10}{'s per 1e6 cells':>18}{'global est. (min)':>20}")
    for stat in footprint.STATISTICS:
        t = time.perf_counter()
        footprint.focal(vals, land, args.radius_km, stat, 0.5)
        dt = time.perf_counter() - t
        per_m = dt / n * 1e6
        print(f"{stat:<14}{dt:>10.1f}{per_m:>18.2f}{per_m * global_land / 1e6 / 60:>20.1f}")
    t = time.perf_counter()
    footprint.focal_many({s: (vals, s) for s in footprint.STATISTICS}, land, args.radius_km, 0.5)
    dt = time.perf_counter() - t
    print(f"{'all (shared)':<14}{dt:>10.1f}{dt / n * 1e6:>18.2f}{dt / n * global_land / 60:>20.1f}")
    print(f"peak RSS {peak_rss_mb():.0f} MB (includes the synthetic mask construction)")
    return 0


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def bench_disk(args) -> int:
    d = Path(args.data_dir)
    if not d.is_dir():
        print(f"{d}: no such directory", file=sys.stderr)
        return 1
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        print(f"{sub.name:<12}{dir_size(sub) / 1e9:>8.2f} GB")
    print(f"{'total':<12}{dir_size(d) / 1e9:>8.2f} GB  (target < 10 GB)")
    return 0


def bench_grid(args) -> int:
    from analogfinder import config
    from analogfinder.grid import build
    from analogfinder.sources.base import SourceRegistry
    from analogfinder.types import StageContext

    config_dir, data_dir = Path(args.config_dir), Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"{data_dir}: no such directory; run `analog grid` once first", file=sys.stderr)
        return 1
    settings = config.load_settings(config_dir)
    ctx = StageContext(
        stage="grid",
        stage_dir=data_dir,
        data_dir=data_dir,
        config_dir=config_dir,
        settings=settings,
        profile=None,
        grid=None,
        sources=SourceRegistry.from_config(config.load_sources(config_dir), data_dir),
        log=logging.getLogger("analogfinder.grid"),
    )
    t = time.perf_counter()
    res = build.build_grid(ctx)
    dt = time.perf_counter() - t
    print(f"grid {res.grid.grid_id} reused={res.reused} wall {dt:.1f} s (target <= 600 s)")
    for layer in res.grid.manifest["layers"]:
        print(" ", layer["layer_id"])
    print(f"peak RSS {peak_rss_mb():.0f} MB (target < 2048 MB)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("footprint")
    f.add_argument("--radius-km", type=float, default=20.0)
    f.add_argument("--band", default="30:40")
    f.add_argument("--land", type=float, default=0.3)
    f.set_defaults(fn=bench_footprint)
    g = sub.add_parser("grid")
    g.add_argument("--data-dir", default="data")
    g.add_argument("--config-dir", default="config")
    g.set_defaults(fn=bench_grid)
    d = sub.add_parser("disk")
    d.add_argument("--data-dir", default="data")
    d.set_defaults(fn=bench_disk)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
