"""Builder type `landcover_fractions` (plan C1, research D-019, task T038).

Driven only by its `config/layers.json` entry (`mcd12c1_landcover`): fetch the yearly product of
`params.year` through the entry's source adapter, read the class-percent SDS named in
`params.sds` with pyhdf (one class band at a time), sum the classes of every group in
`params.class_groups` into fraction layers 0–1 (`lc_frac_<group>`), and derive `land_mask`
from `params.land_rule` (e.g. `"water < 0.5"`: 1 = land, 0 = not land). Native 0.05° CMG, no
resampling. Cells whose class percentages are all missing are NaN in the fraction layers and 0
in the land mask. No product names are hard-coded.

Request sent to the source adapter: `{"short_name": <dataset>, "version": <dataset_version>,
"temporal": ["<year>-01-01", "<year>-12-31"]}`; the returned directory holds the `.hdf` file.
`params.percent_scale` (default 0.01) converts the stored percent values to fractions.
"""

from __future__ import annotations

import logging
import operator
import re
import time
from pathlib import Path

import numpy as np

from ... import storage
from ...errors import ConfigError, SourceError
from .. import cells

log = logging.getLogger("analogfinder.grid.builders.landcover_fractions")

_RULE = re.compile(r"^\s*([a-z0-9_]+)\s*(<=|>=|<|>)\s*([0-9.]+)\s*$")
_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


def parse_land_rule(rule: str, groups) -> tuple[str, object, float]:
    """`"<group> <op> <fraction>"` -> (group, comparison, threshold)."""
    m = _RULE.match(rule or "")
    if not m or m[1] not in groups:
        raise ConfigError(
            f"landcover_fractions: land_rule {rule!r} must be '<group> <op> <value>' with a group "
            f"of params.class_groups ({sorted(groups)})"
        )
    return m[1], _OPS[m[2]], float(m[3])


def resolve_year(params: dict, settings) -> int:
    y = params.get("year")
    if isinstance(y, str) and y.startswith("settings:"):
        node = settings
        for part in y[len("settings:") :].split("."):
            node = node[part]
        y = max(int(v) for v in node) if isinstance(node, list) else node
    if y is None:
        raise ConfigError("landcover_fractions: params.year is required")
    return int(y)


def read_fractions(
    path: Path,
    sds_name: str,
    class_groups: dict,
    percent_scale: float,
    grid_dims: tuple[int, int] = (cells.N_ROWS, cells.N_COLS),
) -> dict:
    """group -> float32 (rows, cols) fraction 0–1 (NaN where no class percentage is valid)."""
    from pyhdf.SD import SD, SDC

    sd = SD(str(path), SDC.READ)
    try:
        sds = sd.select(sds_name)
        _, rank, dims, _, _ = sds.info()
        if rank != 3:
            raise SourceError(f"landcover_fractions: {sds_name} has rank {rank}, expected 3")
        fill = sds.attributes().get("_FillValue")
        # class axis = the axis that is not the grid (MCD12C1: rows, cols, 17 classes)
        grid_dims = tuple(grid_dims)
        if tuple(dims[:2]) == grid_dims:
            axis = 2
        elif tuple(dims[1:]) == grid_dims:
            axis = 0
        else:
            raise SourceError(f"landcover_fractions: {sds_name} dims {dims} do not match grid")
        n_classes = dims[axis]
        wanted = sorted({c for cs in class_groups.values() for c in cs})
        if wanted and wanted[-1] >= n_classes:
            raise ConfigError(
                f"landcover_fractions: class {wanted[-1]} not in {sds_name} ({n_classes} classes)"
            )
        group_of = {c: g for g, cs in class_groups.items() for c in cs}
        sums = {g: np.zeros(grid_dims, dtype="uint16") for g in class_groups}
        valid = np.zeros(grid_dims, dtype=bool)
        for k in range(n_classes):
            band = sds[:, :, k] if axis == 2 else sds[k, :, :]
            band = np.asarray(band)
            ok = np.ones(band.shape, bool) if fill is None else band != fill
            valid |= ok & (band > 0)
            if k in group_of:
                sums[group_of[k]] += np.where(ok, band, 0).astype("uint16")
    finally:
        sd.end()
    out = {}
    for g, s in sums.items():
        frac = s.astype("float32") * np.float32(percent_scale)
        out[g] = np.where(valid, np.clip(frac, 0.0, 1.0), np.float32(np.nan)).astype("float32")
    return out


class LandcoverBuilder:
    """`Builder.build(entry, ctx) -> list[dict]` (manifest layer entries); files go to
    `ctx.stage_dir`. Writes `land_mask.tif` (read by later builders) and `lc_frac_*.tif`."""

    def build(self, entry: dict, ctx) -> list[dict]:
        t0 = time.monotonic()
        params = entry["params"]
        groups: dict = params.get("class_groups") or {}
        if not groups:
            raise ConfigError("landcover_fractions: params.class_groups is empty")
        rule_group, cmp, threshold = parse_land_rule(params.get("land_rule"), groups)
        outputs = {o["layer_id"]: o for o in entry["outputs"]}
        known = {"land_mask"} | {f"lc_frac_{g}" for g in groups}
        unknown = sorted(set(outputs) - known)
        if unknown:
            raise ConfigError(f"landcover_fractions: unknown outputs {unknown}; known {known}")
        year = resolve_year(params, ctx.settings)

        source = ctx.sources.get(entry["source_id"])
        request = {
            "short_name": source.entry["dataset"],
            "version": source.entry["dataset_version"],
            "temporal": [f"{year}-01-01", f"{year}-12-31"],
        }
        res = source.fetch(request)
        files = sorted(Path(res.path).rglob("*.hdf"))
        if not files:
            raise SourceError(f"{entry['source_id']}: no .hdf file for {year} in {res.path}")
        if len(files) > 1:
            log.warning(
                "%s: %d files for %d, using %s", entry["layer_id"], len(files), year, files[0].name
            )
        fractions = read_fractions(
            files[0], params["sds"], groups, float(params.get("percent_scale", 0.01))
        )

        rule_frac = fractions[rule_group]
        land = np.where(np.isfinite(rule_frac), cmp(rule_frac, threshold), False)
        arrays = {"land_mask": land.astype("float32")}
        arrays.update({f"lc_frac_{g}": a for g, a in fractions.items()})
        log.info(
            "%s: %d land cells (%.1f%% of all cells), year %d",
            entry["layer_id"],
            int(land.sum()),
            100.0 * land.mean(),
            year,
        )

        fp = storage.fingerprint(
            {"entry": entry, "dataset_version": source.entry["dataset_version"], "year": year}
        )
        stage_dir = Path(ctx.stage_dir)
        layers = []
        for lid, o in outputs.items():
            name = f"{lid}.tif"
            cells.write_layer(stage_dir / name, arrays[lid])
            layer = {
                "layer_id": lid,
                "quantity": o["quantity"],
                "unit": o["unit"],
                "statistic": o["statistic"],
                "source_id": entry["source_id"],
                "dataset_version": source.entry["dataset_version"],
                "reference_period": str(year),
                "resampling": entry.get("resampling", "none"),
                "file": name,
                "fingerprint": fp,
                "nodata": None,
            }
            if "baseline_m" in o:
                layer["baseline_m"] = o["baseline_m"]
            layers.append(layer)
        log.info("%s built in %.1f s", entry["layer_id"], time.monotonic() - t0)
        return layers
