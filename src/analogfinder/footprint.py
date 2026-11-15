"""Circular footprint statistics on the global 0.05° grid (research D-017, task T046).

For every land cell of a LandIndex: the statistic of a land-aligned layer over all land cells
whose centres lie within `radius_km` (great circle) of that cell's centre.

Method (analysis N3): neighbour gathering on land cells only. For each 1° latitude band the
(row, column) offsets of the circular kernel are precomputed at the band's central latitude
(a fixed radius spans more 0.05° columns towards the poles). An int32 raster maps grid cells
to land-vector indices (−1 = not land); the land cells of a band are processed in chunks of
bounded size: neighbour indices are gathered once into (chunk, k), every layer's values are
taken from them and reduced along the last axis. Columns wrap around the antimeridian; rows
beyond the poles are invalid.

  mean, fraction_true  area-weighted by cos(latitude) of each neighbour
  median, p90, p10     unweighted, linear interpolation (as np.nanpercentile), via np.sort
  max, min             of valid neighbours
Cells whose valid-neighbour fraction is below `min_valid_fraction` -> NaN.
If `radius_km` is smaller than one cell the cell's own value is returned and a warning is
logged (`single_cell(radius_km)` tells the caller to add a note to the criterion result).

Grid geometry defaults to the MODIS CMG (research D-006): 0.05°, row 0 centred at 90 − 0.025°.
"""

from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Mapping

import numpy as np

from .types import LandIndex, Statistic

log = logging.getLogger("analogfinder.footprint")

EARTH_R_KM = 6371.0
CELL_DEG = 0.05
STATISTICS = ("mean", "median", "max", "min", "p90", "p10", "fraction_true")
QUANTILES = {"median": 0.5, "p90": 0.9, "p10": 0.1}


def _hav_km(lat1, lat2, dlon):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(dlon) / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def single_cell(radius_km: float, cell_deg: float = CELL_DEG) -> bool:
    return radius_km < cell_deg * math.pi * EARTH_R_KM / 180


def kernel_offsets(lat: float, radius_km: float, cell_deg: float = CELL_DEG):
    """(drow, dcol) integer offsets of cells within radius of a cell centred at `lat`."""
    max_dr = int(math.ceil(radius_km / (cell_deg * math.pi * EARTH_R_KM / 180))) + 1
    coslat = max(math.cos(math.radians(lat)), 1e-3)
    max_dc = min(int(math.ceil(max_dr / coslat)) + 1, int(round(180 / cell_deg)))
    dr, dc = np.mgrid[-max_dr : max_dr + 1, -max_dc : max_dc + 1]
    # positive drow moves south (row 0 is the north edge)
    d = _hav_km(lat, lat - dr * cell_deg, dc * cell_deg)
    keep = d <= radius_km
    return dr[keep].astype(np.int64), dc[keep].astype(np.int64)


def _nanquantile(vals: np.ndarray, valid: np.ndarray, q: float) -> np.ndarray:
    """Row-wise quantile ignoring NaN, linear interpolation (np.nanpercentile default), via one
    sort per chunk: NaN sort to the end, position q·(n−1) among the n valid values."""
    srt = np.sort(vals, axis=1)
    n = valid.sum(axis=1)
    pos = q * np.maximum(n - 1, 0)
    lo = np.floor(pos).astype(np.int64)
    hi = np.minimum(lo + 1, np.maximum(n - 1, 0))
    rows = np.arange(vals.shape[0])
    a, b = srt[rows, lo], srt[rows, hi]
    return np.where(n > 0, a + (b - a) * (pos - lo), np.nan)


def _reduce(vals: np.ndarray, w: np.ndarray, statistic: str) -> np.ndarray:
    valid = np.isfinite(vals)
    if statistic in ("mean", "fraction_true"):
        x = np.where(valid, vals, 0.0)
        if statistic == "fraction_true":
            x = (x >= 0.5).astype("float64")
        ww = np.where(valid, w, 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            return (x * ww).sum(axis=1) / ww.sum(axis=1)
    if statistic == "max":
        return np.where(valid.any(axis=1), np.where(valid, vals, -np.inf).max(axis=1), np.nan)
    if statistic == "min":
        return np.where(valid.any(axis=1), np.where(valid, vals, np.inf).min(axis=1), np.nan)
    return _nanquantile(vals, valid, QUANTILES[statistic])


def focal(
    values: np.ndarray,
    land: LandIndex,
    radius_km: float,
    statistic: Statistic,
    min_valid_fraction: float,
    **grid,
) -> np.ndarray:
    """Footprint statistic for every land cell (land-aligned in, land-aligned out)."""
    layers = {"x": (values, statistic)}
    return focal_many(layers, land, radius_km, min_valid_fraction, **grid)["x"]


def focal_many(
    layers: Mapping[str, tuple[np.ndarray, Statistic]],
    land: LandIndex,
    radius_km: float,
    min_valid_fraction: float,
    cell_deg: float = CELL_DEG,
    lat_top: float = 90.0,
    grid_shape: tuple[int, int] | None = None,
    wrap_lon: bool = True,
    max_elements: int = 4_000_000,
) -> dict[str, np.ndarray]:
    """Several land-aligned layers in one pass: {name: (values, statistic)} -> {name: values}.

    Neighbour indices are gathered once per chunk and reused for every layer (most of the
    cost). A chunk holds at most `max_elements` gathered values, bounding peak memory
    independently of latitude.
    """
    for name, (_, stat) in layers.items():
        if stat not in STATISTICS:
            raise ValueError(f"{name}: unknown footprint statistic {stat!r}")
    rows = np.asarray(land.rows, dtype=np.int64)
    cols = np.asarray(land.cols, dtype=np.int64)
    n = rows.size
    vals_in = {k: np.asarray(v) for k, (v, _) in layers.items()}  # no float64 copies
    for k, v in vals_in.items():
        if v.shape != (n,):
            raise ValueError(f"{k}: expected a land-aligned vector of length {n}, got {v.shape}")
    out = {k: np.full(n, np.nan) for k in layers}
    if single_cell(radius_km, cell_deg):
        log.warning("radius %.2f km is below one cell: footprint = cell value", radius_km)
        for k, (_, stat) in layers.items():
            v = vals_in[k]
            if stat == "fraction_true":
                out[k] = np.where(np.isfinite(v), (v >= 0.5) * 1.0, np.nan)
            else:
                out[k] = v.astype("float64")
        return out

    nrows, ncols = grid_shape or (int(round(180 / cell_deg)), int(round(360 / cell_deg)))
    lookup = np.full((nrows, ncols), -1, dtype=np.int32)
    lookup[rows, cols] = np.arange(n, dtype=np.int32)
    row_lat = lat_top - (np.arange(nrows) + 0.5) * cell_deg
    row_w = np.cos(np.radians(row_lat))
    bands = np.floor(row_lat[rows]).astype(int)
    for b in np.unique(bands):
        cells = np.nonzero(bands == b)[0]
        dr, dc = kernel_offsets(b + 0.5, radius_km, cell_deg)
        k = dr.size
        chunk = max(1, max_elements // k)
        for s in range(0, cells.size, chunk):
            idx = cells[s : s + chunk]
            nr = rows[idx, None] + dr[None, :]
            nc = cols[idx, None] + dc[None, :]
            if wrap_lon:
                nc %= ncols
            inside = (nr >= 0) & (nr < nrows) & (nc >= 0) & (nc < ncols)
            nr_c = np.clip(nr, 0, nrows - 1)
            nb = np.where(inside, lookup[nr_c, np.clip(nc, 0, ncols - 1)], -1)
            is_land = nb >= 0
            nb_c = np.maximum(nb, 0)
            w = row_w[nr_c]
            for name, (_, stat) in layers.items():
                vals = np.where(is_land, vals_in[name][nb_c].astype("float64"), np.nan)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    res = _reduce(vals, w, stat)
                res[np.isfinite(vals).sum(axis=1) < min_valid_fraction * k] = np.nan
                out[name][idx] = res
    return out
