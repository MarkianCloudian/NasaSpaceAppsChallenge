"""Refinement — fine terrain from NASADEM / Copernicus GLO-30 (plan E3, research D-009, T050).

For an area chosen by the refinement scheduler (T052) the DEM tiles covering a circle of the
profile's `reference_site.radius_km` around the representative point are fetched through
`sources.base.fetch_with_fallback` (cached per request by the source, i.e. per area), mosaicked
over the circle's bounding box, resampled by area-averaging to each criterion's `baseline_m`,
and reduced to

- `slope_p90`: 90th percentile of the Horn slope (degrees) over the circle;
- `rms_roughness`: median over the circle of the local RMS of detrended elevation differences
  at the baseline. For every cell of the resampled grid a 3 x 3 window is taken; its 6
  east-west and 6 north-south neighbour differences (spacing = baseline) have their window
  mean (the local trend) removed, and the RMS of what remains is the cell's roughness (metres).
  A perfect plane gives 0.

Data covering less than `coverage.min_coverage_fraction` of the circle makes the source adapter
layer switch to the source's `fallback` (research D-022); if that is insufficient too, the
values are NaN (UNKNOWN) and `source_id` is None. Same inputs give the same numbers.

DEM source request (what a `stac` adapter must serve): `{"kind": "dem", "bbox": [w, s, e, n]}`
with the bbox in degrees rounded to 4 decimals; the returned cache directory holds one or more
GeoTIFF/COG files (`*.tif`) covering the bbox.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

from ..errors import SourceError
from ..grid.builders.dem_block_stats import EARTH_RADIUS_M, horn_slope_deg
from ..sources.base import fetch_with_fallback
from ..types import CandidateArea, GroupResult

log = logging.getLogger("analogfinder.refine.terrain")

QUANTITIES = ("slope_p90", "rms_roughness")
DEM_SOURCES = ("nasadem-pc", "copdem-glo30-pc")
_FILL = -32768.0
_MIN_BLOCK_VALID = 0.5  # share of valid fine pixels needed for a baseline cell
_MIN_CELLS = 9  # fewer valid baseline cells in the circle -> NaN


def terrain_criteria(profile) -> list:
    """Refinement criteria this module computes (DEM-based earth source, known quantity)."""
    return [
        c
        for c in profile.criteria
        if c.evaluation_scale in ("refinement", "both")
        and c.quantity in QUANTITIES
        and c.baseline_m
        and any(s in DEM_SOURCES for s in c.earth_sources)
    ]


def circle_bbox(lat: float, lon: float, radius_km: float, pad_m: float = 0.0):
    """(west, south, east, north) in degrees around a circle, clipped to the globe."""
    r_m = radius_km * 1000.0 + pad_m
    dlat = math.degrees(r_m / EARTH_RADIUS_M)
    coslat = max(math.cos(math.radians(min(abs(lat) + dlat, 89.9))), 1e-6)
    dlon = math.degrees(r_m / (EARTH_RADIUS_M * coslat))
    return (
        round(max(lon - dlon, -180.0), 4),
        round(max(lat - dlat, -90.0), 4),
        round(min(lon + dlon, 180.0), 4),
        round(min(lat + dlat, 90.0), 4),
    )


def _distance_m(lat, lon, lat0: float, lon0: float) -> np.ndarray:
    """Haversine distance (m) from (lat0, lon0); lat/lon broadcast against each other."""
    p1, p2 = np.radians(lat), math.radians(lat0)
    dphi = p1 - p2
    dl = np.radians(lon - lon0)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def read_mosaic(paths: Sequence[Path], bbox) -> tuple[np.ndarray, rasterio.Affine]:
    """Windowed mosaic of the DEM files over `bbox` -> float64 array with NaN gaps, transform."""
    srcs = [rasterio.open(p) for p in sorted(paths)]
    try:
        nodata = [s.nodata for s in srcs]
        data, transform = merge(srcs, bounds=bbox, nodata=_FILL, dtype="float32")
    finally:
        for s in srcs:
            s.close()
    z = data[0].astype("float64")
    z[z == _FILL] = np.nan
    for nd in {n for n in nodata if n is not None and np.isfinite(n)}:
        z[z == nd] = np.nan
    return z, transform


def _axes(z: np.ndarray, transform) -> tuple[np.ndarray, np.ndarray, float, float]:
    px, py = float(transform.a), float(-transform.e)
    lat = transform.f - py * (np.arange(z.shape[0]) + 0.5)
    lon = transform.c + px * (np.arange(z.shape[1]) + 0.5)
    return lat, lon, px, py


def circle_coverage(z: np.ndarray, transform, lat0: float, lon0: float, radius_km: float) -> float:
    """Fraction of the circle's fine pixels that hold valid elevations."""
    lat, lon, _, _ = _axes(z, transform)
    inside = _distance_m(lat[:, None], lon[None, :], lat0, lon0) <= radius_km * 1000.0
    n = int(inside.sum())
    return float(np.isfinite(z[inside]).sum() / n) if n else 0.0


def area_average(z: np.ndarray, kr: int, kc: int) -> np.ndarray:
    """Block mean over kr x kc pixels (NaN-aware; blocks with < half valid pixels -> NaN)."""
    if kr == 1 and kc == 1:
        return z
    nr, nc = z.shape[0] // kr, z.shape[1] // kc
    blocks = z[: nr * kr, : nc * kc].reshape(nr, kr, nc, kc)
    valid = np.isfinite(blocks).sum(axis=(1, 3))
    total = np.where(np.isfinite(blocks), blocks, 0.0).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = total / valid
    mean[valid < _MIN_BLOCK_VALID * kr * kc] = np.nan
    return mean


def rms_roughness_grid(z: np.ndarray) -> np.ndarray:
    """Local RMS (m) of detrended neighbour differences in 3 x 3 windows (edges -> NaN)."""
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    w = np.lib.stride_tricks.sliding_window_view(z, (3, 3))  # (r-2, c-2, 3, 3)
    dx = w[..., :, 1:] - w[..., :, :-1]  # (.., 3, 2): east-west differences
    dy = w[..., 1:, :] - w[..., :-1, :]  # (.., 2, 3): north-south differences
    dx = dx - dx.mean(axis=(-2, -1), keepdims=True)
    dy = dy - dy.mean(axis=(-2, -1), keepdims=True)
    ss = (dx**2).sum(axis=(-2, -1)) + (dy**2).sum(axis=(-2, -1))
    out[1:-1, 1:-1] = np.sqrt(ss / 12.0)
    return out


def terrain_stats(
    z: np.ndarray,
    transform,
    lat0: float,
    lon0: float,
    radius_km: float,
    baseline_m: float,
) -> dict[str, float]:
    """`{"slope_p90": deg, "rms_roughness": m}` over the circle at `baseline_m` (NaN if sparse)."""
    nan = {"slope_p90": math.nan, "rms_roughness": math.nan}
    lat, _, px, py = _axes(z, transform)
    dy_m = EARTH_RADIUS_M * math.radians(py)
    dx_m = EARTH_RADIUS_M * math.radians(px) * math.cos(math.radians(lat0))
    kr = max(1, round(baseline_m / dy_m))
    kc = max(1, round(baseline_m / dx_m))
    zb = area_average(z, kr, kc)
    if zb.shape[0] < 3 or zb.shape[1] < 3:
        return nan
    nr, nc = zb.shape
    lat_b = lat[: nr * kr].reshape(nr, kr).mean(axis=1)
    lon_b = (transform.c + px * (np.arange(nc * kc) + 0.5))[: nc * kc].reshape(nc, kc).mean(axis=1)
    row_dx = EARTH_RADIUS_M * np.cos(np.radians(lat_b)) * math.radians(px * kc)
    slope = np.full(zb.shape, np.nan)
    slope[1:-1, :] = horn_slope_deg(zb, row_dx[1:-1], EARTH_RADIUS_M * math.radians(py * kr))
    rough = rms_roughness_grid(zb)
    inside = _distance_m(lat_b[:, None], lon_b[None, :], lat0, lon0) <= radius_km * 1000.0
    s, r = slope[inside], rough[inside]
    s, r = s[np.isfinite(s)], r[np.isfinite(r)]
    return {
        "slope_p90": float(np.percentile(s, 90)) if s.size >= _MIN_CELLS else math.nan,
        "rms_roughness": float(np.median(r)) if r.size >= _MIN_CELLS else math.nan,
    }


def _tifs(path: Path) -> list[Path]:
    found = sorted(Path(path).rglob("*.tif")) + sorted(Path(path).rglob("*.tiff"))
    if not found:
        raise SourceError(f"no DEM GeoTIFF in {path}")
    return found


def refine(area: CandidateArea, ctx) -> GroupResult:
    """Terrain group for one scheduler-selected area -> GroupResult(group="terrain")."""
    criteria = terrain_criteria(ctx.profile)
    values: dict[str, float] = {c.id: math.nan for c in criteria}
    if not criteria:
        return GroupResult("terrain", values, None, None)

    lat0, lon0, radius_km = area.footprint
    min_cov = float(ctx.settings["coverage"]["min_coverage_fraction"])
    primary = next(s for s in criteria[0].earth_sources if s in DEM_SOURCES)
    # one cell of margin at the coarsest baseline so edge cells keep their Horn/roughness halo
    pad_m = 2.0 * max(c.baseline_m for c in criteria)
    bbox = circle_bbox(lat0, lon0, radius_km, pad_m)
    request = {"kind": "dem", "bbox": list(bbox)}
    log.info("terrain refinement: %s (%.2f, %.2f) r=%g km", area.area_id, lat0, lon0, radius_km)

    mosaics: dict[Path, tuple[np.ndarray, object]] = {}

    def mosaic(path: Path):
        if path not in mosaics:
            mosaics[path] = read_mosaic(_tifs(path), bbox)
        return mosaics[path]

    def coverage(path: Path) -> float:
        z, tr = mosaic(path)
        return circle_coverage(z, tr, lat0, lon0, radius_km)

    try:
        res = fetch_with_fallback(ctx.sources, primary, request, coverage, min_cov)
    except SourceError as e:
        log.warning("terrain %s: UNKNOWN (%s)", area.area_id, e)
        return GroupResult("terrain", values, None, None)

    z, tr = mosaic(res.path)
    stats_by_baseline: dict[float, dict[str, float]] = {}
    for c in criteria:
        if c.baseline_m not in stats_by_baseline:
            stats_by_baseline[c.baseline_m] = terrain_stats(
                z, tr, lat0, lon0, radius_km, float(c.baseline_m)
            )
        values[c.id] = stats_by_baseline[c.baseline_m][c.quantity]
    log.info("terrain %s: source=%s coverage=%.2f", area.area_id, res.source_id, res.coverage)
    return GroupResult("terrain", values, res.source_id, res.coverage)


def refine_selected(
    areas: Sequence[CandidateArea],
    ctx,
    fn: Callable[[CandidateArea, object], GroupResult] = refine,
) -> dict[str, GroupResult]:
    """Run the terrain pass for the scheduler's selection only; logs how many areas."""
    log.info("terrain refinement: %d area(s) selected by the scheduler", len(areas))
    return {a.area_id: fn(a, ctx) for a in areas}
