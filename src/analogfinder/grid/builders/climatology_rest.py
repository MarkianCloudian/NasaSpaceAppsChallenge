"""Builder type `climatology_rest` (plan C4, research D-008 / D-019, task T041).

Serves a REST climatology source (NASA POWER regional climatology) from a `config/layers.json`
entry. `params.parameters` maps provider parameter -> output `layer_id`; `params.unit_conversions`
maps output `layer_id` -> `{"factor": f, ...}` (value × f). Nothing about parameters, units or
output names is hard-coded here.

Steps: tile the area to fetch (cells of the eligible-land mask in `<stage_dir>/land_mask.tif`
when present, else the whole globe), fetch every (tile, parameter) through the entry's source
adapter (cached: a second build makes zero requests), assemble each parameter on the provider's
native regular grid, resample bilinearly to the 0.05° grid (continuous fields only) and write one
GeoTIFF per output. Native cells without data are ignored in the interpolation (weights are
renormalised), so coastal land cells are filled from neighbouring valid cells.

If the fetch fails or the filled share of land cells is below `params.min_land_fraction`
(default 0.99), a `SourceError` is raised so that `grid/build.py` can run the entry's `fallback`.

Cached tile files: `<PARAMETER>.json` GeoJSON FeatureCollections, one Point per native cell,
`geometry.coordinates = [lon, lat, ...]`, `properties.parameter.<PARAMETER>.{JAN…DEC, ANN}`.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from ... import storage
from ...errors import ConfigError, SourceError
from .. import cells

log = logging.getLogger("analogfinder.grid.builders.climatology_rest")

DEFAULT_ANNUAL_KEY = "ANN"
DEFAULT_MIN_LAND_FRACTION = 0.99
TILE_SIDE_DEG = 10.0  # request tiles are at most this wide; the adapter splits further if needed


def read_tile(path: Path, parameter: str, annual_key: str, fills: tuple) -> list:
    """(lon, lat, value) triples of one cached tile file; fill values are dropped."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for f in data.get("features", []):
        v = f["properties"]["parameter"][parameter].get(annual_key)
        if v is None or any(float(v) == float(x) for x in fills):
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        out.append((float(lon), float(lat), float(v)))
    return out


def assemble_native(points: list) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scatter (lon, lat, value) points onto the regular native grid they lie on.

    The axis steps are the smallest spacing between distinct coordinates; cells never provided
    stay NaN. Returns (lat axis ascending, lon axis ascending, array (n_lat, n_lon)).
    """
    if not points:
        raise SourceError("climatology_rest: no data points in the fetched tiles")
    arr = np.asarray(points, dtype="float64")
    lons, lats, vals = arr[:, 0], arr[:, 1], arr[:, 2]

    def axis(v: np.ndarray) -> tuple[float, float, int]:
        u = np.unique(np.round(v, 6))
        step = float(np.diff(u).min()) if len(u) > 1 else 1.0
        return float(u[0]), step, int(round((u[-1] - u[0]) / step)) + 1

    lon0, dlon, nlon = axis(lons)
    lat0, dlat, nlat = axis(lats)
    grid = np.full((nlat, nlon), np.nan, dtype="float64")
    ci = np.rint((lons - lon0) / dlon).astype(int)
    ri = np.rint((lats - lat0) / dlat).astype(int)
    grid[ri, ci] = vals
    return lat0 + dlat * np.arange(nlat), lon0 + dlon * np.arange(nlon), grid


def _weights(src_axis: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Linear-interpolation indices and weight of the upper neighbour (clamped at the ends)."""
    if len(src_axis) == 1:
        z = np.zeros(len(target), dtype=int)
        return z, z, np.zeros(len(target))
    i1 = np.clip(np.searchsorted(src_axis, target), 1, len(src_axis) - 1)
    i0 = i1 - 1
    w = np.clip((target - src_axis[i0]) / (src_axis[i1] - src_axis[i0]), 0.0, 1.0)
    return i0, i1, w


def bilinear_to_grid(
    lat_ax: np.ndarray, lon_ax: np.ndarray, native: np.ndarray, lat_t: np.ndarray, lon_t: np.ndarray
) -> np.ndarray:
    """Separable bilinear resampling, ignoring NaN native cells (weights renormalised).

    Target cells whose four native neighbours are all NaN stay NaN.
    """
    valid = np.isfinite(native)
    v = np.where(valid, native, 0.0)
    m = valid.astype("float64")
    for axis, src, tgt in ((1, lon_ax, lon_t), (0, lat_ax, lat_t)):
        i0, i1, w = _weights(src, tgt)
        shape = [1, 1]
        shape[axis] = -1
        w = w.reshape(shape)
        v = np.take(v, i0, axis=axis) * (1 - w) + np.take(v, i1, axis=axis) * w
        m = np.take(m, i0, axis=axis) * (1 - w) + np.take(m, i1, axis=axis) * w
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(m > 1e-9, v / np.maximum(m, 1e-9), np.nan)
    return out.astype("float32")


def land_tiles(land: np.ndarray, tile_deg: float = TILE_SIDE_DEG) -> list[tuple]:
    """Bounding boxes `(lon_min, lat_min, lon_max, lat_max)` of the `tile_deg` blocks that
    contain land cells (padded by one block cell row/column so edge cells have neighbours)."""
    step = int(round(tile_deg / cells.CELL_DEG))
    boxes = []
    for r0 in range(0, cells.N_ROWS, step):
        for c0 in range(0, cells.N_COLS, step):
            if land[r0 : r0 + step, c0 : c0 + step].any():
                boxes.append(
                    (
                        cells.ORIGIN_LON + c0 * cells.CELL_DEG,
                        cells.ORIGIN_LAT - min(r0 + step, cells.N_ROWS) * cells.CELL_DEG,
                        cells.ORIGIN_LON + min(c0 + step, cells.N_COLS) * cells.CELL_DEG,
                        cells.ORIGIN_LAT - r0 * cells.CELL_DEG,
                    )
                )
    return boxes


def _load_land(stage_dir: Path) -> np.ndarray | None:
    path = stage_dir / "land_mask.tif"
    if not path.is_file():
        return None
    return np.nan_to_num(cells.read_layer(path), nan=0.0) > 0.5


class ClimatologyRestBuilder:
    """`Builder.build(entry, ctx) -> list[dict]` (manifest layer entries); files go to
    `ctx.stage_dir`."""

    def build(self, entry: dict, ctx) -> list[dict]:
        t0 = time.monotonic()
        params = entry["params"]
        parameters: dict = params.get("parameters") or {}
        conversions: dict = params.get("unit_conversions") or {}
        if not parameters:
            raise ConfigError("climatology_rest: params.parameters is empty")
        outputs = {o["layer_id"]: o for o in entry["outputs"]}
        missing = sorted(set(parameters.values()) - set(outputs))
        if missing:
            raise ConfigError(f"climatology_rest: outputs lack layer ids {missing}")
        annual_key = params.get("annual_key", DEFAULT_ANNUAL_KEY)
        fills = tuple(params.get("fill_values", (-999,)))
        min_land = float(params.get("min_land_fraction", DEFAULT_MIN_LAND_FRACTION))

        source = ctx.sources.get(entry["source_id"])
        stage_dir = Path(ctx.stage_dir)
        land = _load_land(stage_dir)
        if land is not None:
            boxes = land_tiles(land)
        else:
            log.warning("climatology_rest: no land_mask.tif in stage dir; fetching the globe")
            boxes = [(-180.0, -90.0, 180.0, 90.0)]
        if not boxes:
            raise SourceError("climatology_rest: land mask contains no land")

        results = []
        for box in boxes:
            results.extend(source.fetch_tiles(box, tuple(parameters)))
        log.info("%s: %d tile fetches", entry["layer_id"], len(results))

        lat_t, lon_t = cells.cell_centres()
        fp = storage.fingerprint(
            {"entry": entry, "dataset_version": source.entry["dataset_version"]}
        )
        layers = []
        for parameter, out_id in parameters.items():
            points: list = []
            for res in results:
                f = Path(res.path) / f"{parameter}.json"
                if not f.is_file():
                    raise SourceError(f"{entry['source_id']}: {f.name} missing in {res.path}")
                points.extend(read_tile(f, parameter, annual_key, fills))
            lat_ax, lon_ax, native = assemble_native(points)
            native = native * float(conversions.get(out_id, {}).get("factor", 1.0))
            array = bilinear_to_grid(lat_ax, lon_ax, native, lat_t, lon_t)
            if land is not None:
                filled = float(np.isfinite(array[land]).mean())
                if filled < min_land:
                    raise SourceError(
                        f"{entry['source_id']}: {out_id} fills {filled:.1%} of land cells "
                        f"(< {min_land:.0%}); use the fallback"
                    )
            name = f"{out_id}.tif"
            cells.write_layer(stage_dir / name, array)
            o = outputs[out_id]
            layer = {
                "layer_id": o["layer_id"],
                "quantity": o["quantity"],
                "unit": o["unit"],
                "statistic": o["statistic"],
                "source_id": entry["source_id"],
                "dataset_version": source.entry["dataset_version"],
                "reference_period": params.get("reference_period", "provider climatology"),
                "resampling": entry.get("resampling", "bilinear"),
                "file": name,
                "fingerprint": fp,
                "nodata": None,
            }
            if "baseline_m" in o:
                layer["baseline_m"] = o["baseline_m"]
            layers.append(layer)
        log.info("%s built in %.1f s", entry["layer_id"], time.monotonic() - t0)
        return layers
