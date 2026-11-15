"""Builder type `modis_cmg` (plan C2, research D-019, task T039).

Serves any MODIS 0.05° CMG monthly HDF4 product from a `config/layers.json` entry. The entry's
`params` name the variables (`variables`: role -> SDS name), the scale and offset, the QC rule
(`qc`) and the reference years. Steps: fetch the monthly files of every reference year through
the entry's source adapter; read the SDS with pyhdf; mask fill values and cells failing the QC
rule; scale (`raw * scale + offset_c`); average per calendar month across years; compute the
outputs listed in the entry.

Output recipes are keyed by output `layer_id` in `OUTPUT_RECIPES` (all statistics are of
*monthly means*, which smooth daily extremes). The QC rule is decoded here per the product user
guide and recorded in every manifest layer entry as `qc_rule`.

Request sent to the source adapter, one per reference year (global, no bounding box):
`{"short_name": <dataset>, "version": <dataset_version>, "temporal": [start, end]}`; the returned
directory must contain the year's monthly `*.hdf` files (`<PRODUCT>.A<YYYY><DDD>.…hdf`, DDD =
day of year of the first day of the month).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from pathlib import Path

import numpy as np

from ... import storage
from ...errors import ConfigError, SourceError
from .. import cells

log = logging.getLogger("analogfinder.grid.builders.modis_cmg")

_FILE_DATE = re.compile(r"\.A(\d{4})(\d{3})\.")

# QC rules: name -> (human-readable description, function(qc_raw ndarray) -> bool keep mask).
# MOD11C3 QC_Day / QC_Night (uint8), bits 0-1 = mandatory QA: 00 LST produced, good quality;
# 01 LST produced, other quality; 10 LST not produced (clouds); 11 not produced (other).
# MOD13C2 pixel reliability (int8): -1 fill, 0 good, 1 marginal, 2 snow/ice, 3 cloudy.
QC_RULES: dict = {
    "mandatory_qa_good_or_other_quality": (
        "QC bits 0-1 (mandatory QA) in {00 good, 01 other quality}; 10 and 11 rejected",
        lambda qc: (qc.astype(np.uint8) & 0b11) <= 1,
    ),
    "good_or_marginal": (
        "pixel reliability in {0 good, 1 marginal}; -1 fill, 2 snow/ice, 3 cloudy rejected",
        lambda qc: (qc.astype(np.int16) >= 0) & (qc.astype(np.int16) <= 1),
    ),
}


def _stat_nan(fn, stack: np.ndarray) -> np.ndarray:
    """Reduce axis 0 ignoring NaN; all-NaN cells stay NaN without warnings."""
    valid = ~np.isnan(stack)
    any_valid = valid.any(axis=0)
    if fn is np.nanmean:
        total = np.where(valid, stack, 0.0).sum(axis=0)
        out = total / np.maximum(valid.sum(axis=0), 1)
    else:
        fill = -np.inf if fn is np.nanmax else np.inf
        red = np.max if fn is np.nanmax else np.min
        out = red(np.where(valid, stack, fill), axis=0)
    return np.where(any_valid, out, np.nan).astype("float32")


# Output recipe per output layer_id: function(monthly dict role -> (12, rows, cols)) -> array.
def _day_max(m):
    return _stat_nan(np.nanmax, m["day"])


def _night_min(m):
    return _stat_nan(np.nanmin, m["night"])


def _mean(m):
    both = (m["day"] + m["night"]) / 2.0  # NaN if either is missing in that month
    return _stat_nan(np.nanmean, both)


def _amp(m):
    return _stat_nan(np.nanmean, m["day"] - m["night"])


OUTPUT_RECIPES = {
    "lst_day_max": (_day_max, ("day",)),
    "lst_night_min": (_night_min, ("night",)),
    "lst_mean": (_mean, ("day", "night")),
    "lst_amp": (_amp, ("day", "night")),
}


def decode_qc(rule: str, qc: np.ndarray) -> np.ndarray:
    """Boolean keep-mask for the named QC rule."""
    if rule not in QC_RULES:
        raise ConfigError(f"modis_cmg: unknown qc rule {rule!r}; known: {sorted(QC_RULES)}")
    return QC_RULES[rule][1](qc)


def read_month(path: Path, variables: dict, scale: float, offset: float, qc: dict) -> dict:
    """Read one monthly HDF4 file -> role -> float32 array (NaN where fill or failing QC)."""
    from pyhdf.SD import SD, SDC

    sd = SD(str(path), SDC.READ)
    try:
        out = {}
        for role, sds_name in variables.items():
            sds = sd.select(sds_name)
            raw = sds.get()
            attrs = sds.attributes()
            fill = attrs.get("_FillValue")
            valid = np.ones(raw.shape, dtype=bool) if fill is None else raw != fill
            qc_name = qc.get(role)
            if qc_name:
                valid &= decode_qc(qc["keep"], sd.select(qc_name).get())
            vals = raw.astype("float32") * np.float32(scale) + np.float32(offset)
            out[role] = np.where(valid, vals, np.float32(np.nan))
        return out
    finally:
        sd.end()


def month_of(path: Path) -> int:
    """Calendar month (1-12) from the `A<YYYY><DDD>` token of a MODIS file name."""
    m = _FILE_DATE.search(path.name)
    if not m:
        raise SourceError(f"modis_cmg: cannot read acquisition date from {path.name!r}")
    return (dt.date(int(m[1]), 1, 1) + dt.timedelta(days=int(m[2]) - 1)).month


def climatology(files: list[Path], params: dict) -> dict:
    """role -> (12, rows, cols) mean over years per calendar month (NaN where never valid)."""
    variables = params["variables"]
    offset = float(params.get("offset_c", 0.0))
    scale = float(params["scale"])
    qc = params.get("qc") or {}
    sums: dict = {}
    counts: dict = {}
    for f in sorted(files):
        mi = month_of(f) - 1
        data = read_month(f, variables, scale, offset, qc)
        for role, arr in data.items():
            if role not in sums:
                sums[role] = np.zeros((12,) + arr.shape, dtype="float64")
                counts[role] = np.zeros((12,) + arr.shape, dtype="uint16")
            ok = ~np.isnan(arr)
            sums[role][mi][ok] += arr[ok]
            counts[role][mi] += ok
    out = {}
    for role in sums:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[role] = np.where(
                counts[role] > 0, sums[role] / np.maximum(counts[role], 1), np.nan
            ).astype("float32")
    return out


def resolve_years(params: dict, settings) -> list[int]:
    ry = params["reference_years"]
    if isinstance(ry, str):
        if not ry.startswith("settings:"):
            raise ConfigError(f"modis_cmg: bad reference_years {ry!r}")
        node = settings
        for part in ry[len("settings:") :].split("."):
            node = node[part]
        ry = node
    years = sorted(int(y) for y in ry)
    if not years:
        raise ConfigError("modis_cmg: empty reference_years")
    return years


class ModisCmgBuilder:
    """`Builder.build(entry, ctx) -> list[dict]` (manifest layer entries); files go to
    `ctx.stage_dir`."""

    def build(self, entry: dict, ctx) -> list[dict]:
        t0 = time.monotonic()
        params = entry["params"]
        source = ctx.sources.get(entry["source_id"])
        years = resolve_years(params, ctx.settings)
        for output in entry["outputs"]:
            if output["layer_id"] not in OUTPUT_RECIPES:
                raise ConfigError(f"modis_cmg: no recipe for output {output['layer_id']!r}")
        qc = params.get("qc") or {}
        qc_rule = QC_RULES[qc["keep"]][0] if qc.get("keep") in QC_RULES else None
        if qc.get("keep") and qc_rule is None:
            raise ConfigError(f"modis_cmg: unknown qc rule {qc['keep']!r}")

        files: list[Path] = []
        for y in years:
            request = {
                "short_name": source.entry["dataset"],
                "version": source.entry["dataset_version"],
                "temporal": [f"{y}-01-01", f"{y}-12-31"],
            }
            res = source.fetch(request)
            found = sorted(Path(res.path).rglob("*.hdf"))
            if not found:
                raise SourceError(f"{entry['source_id']}: no .hdf files for {y}")
            files.extend(found)
        log.info("%s: %d monthly files, years %s", entry["layer_id"], len(files), years)

        monthly = climatology(files, params)
        needed = {r for o in entry["outputs"] for r in OUTPUT_RECIPES[o["layer_id"]][1]}
        missing = needed - set(monthly)
        if missing:
            raise ConfigError(f"modis_cmg: params.variables lacks roles {sorted(missing)}")

        fp = storage.fingerprint(
            {"entry": entry, "dataset_version": source.entry["dataset_version"], "years": years}
        )
        stage_dir = Path(ctx.stage_dir)
        layers = []
        for o in entry["outputs"]:
            fn, _roles = OUTPUT_RECIPES[o["layer_id"]]
            array = fn(monthly)
            name = f"{o['layer_id']}.tif"
            cells.write_layer(stage_dir / name, array)
            layer = {
                "layer_id": o["layer_id"],
                "quantity": o["quantity"],
                "unit": o["unit"],
                "statistic": o["statistic"],
                "source_id": entry["source_id"],
                "dataset_version": source.entry["dataset_version"],
                "reference_period": f"{years[0]}-{years[-1]}",
                "resampling": entry.get("resampling", "none"),
                "file": name,
                "fingerprint": fp,
                "nodata": None,
            }
            if qc_rule:
                layer["qc_rule"] = f"{qc['keep']}: {qc_rule}"
            if "baseline_m" in o:
                layer["baseline_m"] = o["baseline_m"]
            layers.append(layer)
        log.info("%s built in %.1f s", entry["layer_id"], time.monotonic() - t0)
        return layers
