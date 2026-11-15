"""T047: benchmark `footprint.focal` on the real grid's land cells (research D-017, analysis N3).

Runs every grid-scale criterion of the Mars v1 profile (`hyperarid` mean, `dry_air` mean,
`no_vegetation` p90, `barren_ground` mean, `thermal_swing` mean, `regional_slope` p90) at the
profile radius over all land cells of a built grid, each in its own process (clean peak RSS),
then all six in one `focal_many` pass (what screening, T048, runs).

Run time depends on the land cells (count, latitude distribution) and the kernel, not on the
layer values. Layers present in the grid are used as they are; a layer that is not in the grid
(e.g. when only the land-cover layer was built) is replaced by a fixed-seed random field, and
the script says so.

Usage:
  python scripts/benchmark_footprint_real.py --grid data/grids/<grid_id> [--radius-km 20]
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time

import numpy as np

CRITERIA = [  # (criterion id, layer id, footprint statistic) of the Mars v1 profile
    ("hyperarid", "precip_annual", "mean"),
    ("dry_air", "rh2m_mean", "mean"),
    ("no_vegetation", "ndvi_max", "p90"),
    ("barren_ground", "lc_frac_barren", "mean"),
    ("thermal_swing", "lst_amp", "mean"),
    ("regional_slope", "slope_p90_1km", "p90"),
]


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KiB


def worker(grid_path: str, radius: float, which: str, min_valid: float, lat_range=None) -> dict:
    from analogfinder import footprint
    from analogfinder.grid.build import load_grid

    t0 = time.monotonic()
    grid = load_grid(grid_path)
    land = grid.land_index()
    have = {e["layer_id"] for e in grid.manifest["layers"]}
    rng = np.random.default_rng(0)
    jobs, synthetic = {}, []
    for cid, layer, stat in CRITERIA:
        if which not in ("all", cid):
            continue
        if layer in have:
            v = grid.land_vector(layer).astype("float32")
        else:
            v = rng.random(land.rows.size, dtype=np.float32)
            synthetic.append(layer)
        jobs[cid] = (v, stat)
    t_load = time.monotonic() - t0
    targets = None
    if lat_range:
        targets = (land.lat >= lat_range[0]) & (land.lat <= lat_range[1])
    t1 = time.monotonic()
    out = footprint.focal_many(jobs, land, radius, min_valid, targets=targets)
    t_focal = time.monotonic() - t1
    valid = {k: float(np.isfinite(v).mean()) for k, v in out.items()}
    n_t = int(land.rows.size if targets is None else targets.sum())
    return {
        "which": which,
        "land_cells": int(land.rows.size),
        "target_cells": n_t,
        "load_s": round(t_load, 1),
        "focal_s": round(t_focal, 1),
        "peak_rss_mb": round(peak_rss_mb()),
        "synthetic_layers": synthetic,
        "valid_fraction": valid,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--grid", required=True)
    ap.add_argument("--radius-km", type=float, default=20.0)
    ap.add_argument("--min-valid-fraction", type=float, default=0.5)
    ap.add_argument(
        "--lat-range",
        nargs=2,
        type=float,
        metavar=("SOUTH", "NORTH"),
        help="compute only cells in this latitude range (profile search constraint)",
    )
    ap.add_argument("--only-all", action="store_true", help="skip the per-criterion runs")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.worker:
        print(json.dumps(worker(a.grid, a.radius_km, a.worker, a.min_valid_fraction, a.lat_range)))
        return 0
    rows = []
    for which in ([] if a.only_all else [c[0] for c in CRITERIA]) + ["all"]:
        cmd = [
            sys.executable,
            __file__,
            "--grid",
            a.grid,
            "--radius-km",
            str(a.radius_km),
            "--min-valid-fraction",
            str(a.min_valid_fraction),
            "--worker",
            which,
        ]
        if a.lat_range:
            cmd += ["--lat-range", str(a.lat_range[0]), str(a.lat_range[1])]
        res = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)
        rows.append(res)
        print(
            f"{which:15s} focal {res['focal_s']:7.1f} s  load {res['load_s']:5.1f} s  "
            f"peak RSS {res['peak_rss_mb']:5d} MB  land cells {res['land_cells']}"
            f"  computed {res['target_cells']}"
            + (
                f"  synthetic: {', '.join(res['synthetic_layers'])}"
                if res["synthetic_layers"]
                else ""
            ),
            flush=True,
        )
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
