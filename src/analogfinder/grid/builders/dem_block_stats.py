"""Builder type `dem_block_stats` (plan C5, research D-009 / D-019 / D-023, task T042).

Any global GeoTIFF DEM -> Horn slope at the native resolution -> statistics of each
`params.block` x `params.block` block (one 0.05° cell): `slope_p90_1km`, `relief`, `elev_std`,
`elev_mean`. The block size, slope method and outputs (with `baseline_m`) come from the
`config/layers.json` entry.

Memory: the raster is read in row bands (one output row = `block` source rows plus a 1-row halo
on each side), never as a whole; peak RAM is a few hundred MB for ETOPO 30″.

Registration (D-023), detected from the GeoTIFF transform and size:

* cell-registered: origin (-180, 90), `360/px x 180/px` pixels -> blocks used directly;
* grid-registered (nodes on the pixel corners): origin (-180 - px/2, 90 + px/2), one extra
  column and row -> the last column (+180 duplicates -180) and last row (-90) are dropped, nodes
  are assigned to cell `floor((lon + 180)/0.05)`, `floor((90 - lat)/0.05)` (edge nodes go
  east/south). With node spacing `px = 0.05/block` that is exactly `block` nodes per cell and
  per axis, so the assignment is the integer block `index // block`;
* anything else -> `ConfigError` listing what was found.

Slope is always computed on the native array (including the dropped last row/column as halo)
before the blocks are aggregated.
"""

from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

from ... import storage
from ...errors import ConfigError, SourceError
from .. import cells

log = logging.getLogger("analogfinder.grid.builders.dem_block_stats")

EARTH_RADIUS_M = 6371008.8  # mean radius (IUGG), same sphere as cells.EARTH_RADIUS_KM
TOL = 1e-6  # degrees, tolerance when comparing transform values
STATS = ("slope_p90_1km", "relief", "elev_std", "elev_mean")
SLOPE_METHODS = ("horn",)


@dataclass(frozen=True, slots=True)
class Registration:
    kind: str  # "cell" | "grid"
    half_pixel_offset_deg: float  # 0 for cell-registered, px/2 for grid-registered
    n_rows: int  # output cells
    n_cols: int
    pixel_deg: float


def detect_registration(
    width: int,
    height: int,
    transform,
    block: int,
    cell_deg: float = cells.CELL_DEG,
) -> Registration:
    """Classify the raster geometry (research D-023) or raise `ConfigError` with what was found."""
    px = cell_deg / block
    n_cols = int(round(360.0 / cell_deg))
    n_rows = int(round(180.0 / cell_deg))
    cols0, rows0 = n_cols * block, n_rows * block
    found = (
        f"found size {width} x {height}, origin ({transform.c}, {transform.f}), "
        f"pixel ({transform.a}, {transform.e})"
    )
    north_up = (
        abs(transform.a - px) < TOL * px
        and abs(transform.e + px) < TOL * px
        and abs(transform.b) < TOL
        and abs(transform.d) < TOL
    )
    cell = (
        abs(transform.c + 180.0) < TOL
        and abs(transform.f - 90.0) < TOL
        and (width, height) == (cols0, rows0)
    )
    grid = (
        abs(transform.c + 180.0 + px / 2) < TOL
        and abs(transform.f - 90.0 - px / 2) < TOL
        and (width, height) == (cols0 + 1, rows0 + 1)
    )
    if north_up and cell:
        return Registration("cell", 0.0, n_rows, n_cols, px)
    if north_up and grid:
        return Registration("grid", px / 2, n_rows, n_cols, px)
    raise ConfigError(
        "dem_block_stats: unsupported DEM geometry; expected cell-registered "
        f"(origin -180, 90; {cols0} x {rows0}; pixel {px:.10g}) or grid-registered "
        f"(origin {-180 - px / 2:.10g}, {90 + px / 2:.10g}; {cols0 + 1} x {rows0 + 1}); " + found
    )


def horn_slope_deg(
    z: np.ndarray, dx_m: np.ndarray, dy_m: float, wrap: bool = False, dup_last: bool = False
) -> np.ndarray:
    """Horn slope (degrees) of the interior rows of `z` (rows 1..-2 are returned).

    `z` has one halo row above and below; `dx_m` is the east-west spacing in metres per row of
    the returned array. Columns: periodic when `wrap` (global raster; with `dup_last` the last
    column repeats the first, as in grid-registered rasters), else edge-replicated.
    NaN anywhere in a 3 x 3 window gives NaN.
    """
    z = z.astype("float64", copy=False)
    if wrap:
        west, east = (z[:, -2:-1], z[:, 1:2]) if dup_last else (z[:, -1:], z[:, :1])
        zp = np.concatenate([west, z, east], axis=1)
    else:
        zp = np.pad(z, ((0, 0), (1, 1)), mode="edge")
    a, b, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    d, f = zp[1:-1, :-2], zp[1:-1, 2:]
    g, h, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * dx_m[:, None])
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8.0 * dy_m)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))


def _blocks(a: np.ndarray, block: int, n_cols: int) -> np.ndarray:
    """(block, W) band -> (n_cols, block*block): the values of every block."""
    a = a[:, : n_cols * block]
    return a.reshape(block, n_cols, block).transpose(1, 0, 2).reshape(n_cols, block * block)


def block_stats(
    path: Path,
    block: int = 6,
    cell_deg: float = cells.CELL_DEG,
    nodata: float | None = None,
) -> tuple[dict[str, np.ndarray], Registration]:
    """Stream the DEM in row bands and return `{STATS name: float32 array (n_rows, n_cols)}`."""
    with rasterio.open(path) as src:
        reg = detect_registration(src.width, src.height, src.transform, block, cell_deg)
        if nodata is None:
            nodata = src.nodata
        height, width = src.height, src.width
        top = src.transform.f
        dy_m = EARTH_RADIUS_M * np.radians(reg.pixel_deg)
        out = {k: np.full((reg.n_rows, reg.n_cols), np.nan, dtype="float32") for k in STATS}
        for r in range(reg.n_rows):
            r0, r1 = r * block, (r + 1) * block  # source rows of this output row
            lo, hi = max(r0 - 1, 0), min(r1 + 1, height)
            data = src.read(1, window=((lo, hi), (0, width))).astype("float64")
            if nodata is not None and np.isfinite(nodata):
                data[data == nodata] = np.nan
            if lo > r0 - 1:  # pole edge: replicate the first row as halo
                data = np.vstack([data[:1], data])
            if hi < r1 + 1:
                data = np.vstack([data, data[-1:]])
            lat = top - (np.arange(r0 - 1, r1 + 1, dtype="float64")[1:-1] + 0.5) * reg.pixel_deg
            dx_m = np.maximum(
                EARTH_RADIUS_M * np.radians(reg.pixel_deg) * np.cos(np.radians(lat)), 1.0
            )
            slope = _blocks(
                horn_slope_deg(data, dx_m, dy_m, True, reg.kind == "grid"), block, reg.n_cols
            )
            elev = _blocks(data[1:-1], block, reg.n_cols)
            with warnings.catch_warnings():  # all-NaN blocks (no data) stay NaN
                warnings.simplefilter("ignore", RuntimeWarning)
                out["slope_p90_1km"][r] = np.nanpercentile(slope, 90, axis=1)
                out["relief"][r] = np.nanmax(elev, axis=1) - np.nanmin(elev, axis=1)
                out["elev_std"][r] = np.nanstd(elev, axis=1)
                out["elev_mean"][r] = np.nanmean(elev, axis=1)
    return out, reg


class DemBlockStatsBuilder:
    """`Builder.build(entry, ctx) -> list[dict]` (manifest layer entries); files go to
    `ctx.stage_dir`."""

    def build(self, entry: dict, ctx) -> list[dict]:
        t0 = time.monotonic()
        params = entry["params"]
        block = int(params.get("block", 6))
        method = params.get("slope_method", "horn")
        if method not in SLOPE_METHODS:
            raise ConfigError(f"dem_block_stats: unknown slope_method {method!r}")
        outputs = {o["layer_id"]: o for o in entry["outputs"]}
        unknown = sorted(set(outputs) - set(STATS))
        if unknown:
            raise ConfigError(f"dem_block_stats: unknown outputs {unknown}; known {list(STATS)}")

        source = ctx.sources.get(entry["source_id"])
        res = source.fetch({"url": source.entry["endpoint"], "file": "dem.tif"})
        tifs = sorted(Path(res.path).rglob("*.tif"))
        if not tifs:
            raise SourceError(f"{entry['source_id']}: no GeoTIFF in {res.path}")
        stats, reg = block_stats(tifs[0], block)
        if (reg.n_rows, reg.n_cols) != (cells.N_ROWS, cells.N_COLS):
            raise ConfigError(
                f"dem_block_stats: block {block} gives {reg.n_rows} x {reg.n_cols} cells, "
                f"grid is {cells.N_ROWS} x {cells.N_COLS}"
            )
        log.info("%s: %s-registered DEM", entry["layer_id"], reg.kind)

        fp = storage.fingerprint(
            {"entry": entry, "dataset_version": source.entry["dataset_version"]}
        )
        layers = []
        for lid, o in outputs.items():
            name = f"{lid}.tif"
            cells.write_layer(Path(ctx.stage_dir) / name, stats[lid])
            layer = {
                "layer_id": lid,
                "quantity": o["quantity"],
                "unit": o["unit"],
                "statistic": o["statistic"],
                "source_id": entry["source_id"],
                "dataset_version": source.entry["dataset_version"],
                "resampling": entry.get("resampling", "block_stats"),
                "file": name,
                "fingerprint": fp,
                "nodata": None,
                "registration": {
                    "kind": reg.kind,
                    "half_pixel_offset_deg": reg.half_pixel_offset_deg,
                },
            }
            if "baseline_m" in o:
                layer["baseline_m"] = o["baseline_m"]
            layers.append(layer)
        log.info("%s built in %.1f s", entry["layer_id"], time.monotonic() - t0)
        return layers
