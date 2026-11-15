"""Builder type `modis_cmg` (plan C2, research D-019, task T039).

Serves any MODIS 0.05° CMG monthly HDF4 product from a `config/layers.json` entry. The entry's
`params` name the variables (`variables`: role -> SDS name), the scale and offset, the QC rule
(`qc`) and the reference years. Steps: fetch the monthly files of every reference year through
the entry's source adapter; read the SDS with pyhdf; mask fill values and cells failing the QC
rule; scale (`raw * scale + offset_c`); average per calendar month across years; compute the
outputs listed in the entry.

Outputs without a recipe use the generic `params.temporal_reduce` (`max`/`min`/`mean` over the
12 calendar-month means of the single variable); this is how NDVI is served (no product code).

Output recipes are keyed by output `layer_id` in `OUTPUT_EXPRS` (all statistics are of
*monthly means*, which smooth daily extremes). The QC rule is decoded here per the product user
guide and recorded in every manifest layer entry as `qc_rule`.

Memory: the builder streams one calendar month at a time (mean over the years of that month,
then folded into a running max / min / mean per output), so peak RAM stays about 1 GB for the
global 3600 x 7200 grid instead of holding twelve float64 monthly stacks per variable.

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


# Generic temporal reduction over the 12 calendar-month climatology of the single variable,
# selected by `params.temporal_reduce` (used by outputs without a dedicated recipe, e.g. NDVI max).
TEMPORAL_REDUCE = {
    "max": np.nanmax,
    "min": np.nanmin,
    "mean": np.nanmean,
}

# Output definition per output layer_id: (temporal reduction over the 12 monthly means,
# per-month expression of the month's role arrays, roles needed). Elementwise expressions work on
# one month (rows, cols) and on a (12, rows, cols) stack alike; NaN in any role gives NaN.
OUTPUT_EXPRS: dict = {
    "lst_day_max": ("max", lambda m: m["day"], ("day",)),
    "lst_night_min": ("min", lambda m: m["night"], ("night",)),
    "lst_mean": ("mean", lambda m: (m["day"] + m["night"]) / 2.0, ("day", "night")),
    "lst_amp": ("mean", lambda m: m["day"] - m["night"], ("day", "night")),
}


def _recipe(reduce: str, expr):
    return lambda m: _stat_nan(TEMPORAL_REDUCE[reduce], expr(m))


# Whole-stack form, function(monthly dict role -> (12, rows, cols)) -> array (tests, small data).
OUTPUT_RECIPES = {lid: (_recipe(r, e), roles) for lid, (r, e, roles) in OUTPUT_EXPRS.items()}


def temporal_reduce_expr(params: dict):
    """(reduce name, expression, roles) for the only variable of `params`."""
    name = params.get("temporal_reduce")
    if name not in TEMPORAL_REDUCE:
        raise ConfigError(
            f"modis_cmg: unknown temporal_reduce {name!r}; known: {sorted(TEMPORAL_REDUCE)}"
        )
    roles = list(params["variables"])
    if len(roles) != 1:
        raise ConfigError("modis_cmg: temporal_reduce needs exactly one entry in params.variables")
    role = roles[0]
    return name, (lambda m: m[role]), (role,)


def temporal_reduce_recipe(params: dict):
    """(function, roles) reducing the only variable of `params` with `params.temporal_reduce`."""
    name, expr, roles = temporal_reduce_expr(params)
    return _recipe(name, expr), roles


class RunningReduce:
    """Fold monthly arrays one at a time into max / min / mean, ignoring NaN (= `_stat_nan`)."""

    def __init__(self, kind: str):
        if kind not in TEMPORAL_REDUCE:
            raise ConfigError(f"modis_cmg: unknown reduction {kind!r}")
        self.kind = kind
        self.acc: np.ndarray | None = None
        self.n: np.ndarray | None = None

    def add(self, a: np.ndarray) -> None:
        a = np.asarray(a, dtype="float32")
        if self.kind == "mean":
            ok = ~np.isnan(a)
            if self.acc is None:
                self.acc = np.zeros(a.shape, dtype="float32")
                self.n = np.zeros(a.shape, dtype="uint8")
            self.acc[ok] += a[ok]
            self.n += ok
        elif self.acc is None:
            self.acc = a.copy()
        else:
            (np.fmax if self.kind == "max" else np.fmin)(self.acc, a, out=self.acc)

    def result(self) -> np.ndarray | None:
        if self.acc is None:
            return None
        if self.kind == "mean":
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(self.n > 0, self.acc / np.maximum(self.n, 1), np.nan).astype(
                    "float32"
                )
        return self.acc


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


def by_month(files: list[Path]) -> dict[int, list[Path]]:
    """Calendar month (1-12) -> its files (all years), sorted."""
    out: dict[int, list[Path]] = {}
    for f in sorted(files):
        out.setdefault(month_of(f), []).append(f)
    return out


def month_mean(files: list[Path], params: dict) -> dict:
    """role -> (rows, cols) float32 mean over the given files (one calendar month, all years);
    NaN where no year is valid."""
    variables = params["variables"]
    offset = float(params.get("offset_c", 0.0))
    scale = float(params["scale"])
    qc = params.get("qc") or {}
    sums: dict = {}
    counts: dict = {}
    for f in sorted(files):
        data = read_month(f, variables, scale, offset, qc)
        for role, arr in data.items():
            if role not in sums:
                sums[role] = np.zeros(arr.shape, dtype="float32")
                counts[role] = np.zeros(arr.shape, dtype="uint8")
            ok = ~np.isnan(arr)
            sums[role][ok] += arr[ok]
            counts[role] += ok
        del data
    out = {}
    for role in sums:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[role] = np.where(
                counts[role] > 0, sums[role] / np.maximum(counts[role], 1), np.nan
            ).astype("float32")
    return out


def climatology(files: list[Path], params: dict) -> dict:
    """role -> (12, rows, cols) mean over years per calendar month (NaN where never valid).

    Holds all twelve months in memory: for small inputs and tests; the builder streams."""
    months = by_month(files)
    per_month = {mi: month_mean(fs, params) for mi, fs in months.items()}
    out = {}
    for role in {r for mm in per_month.values() for r in mm}:
        shape = next(mm[role].shape for mm in per_month.values() if role in mm)
        stack = np.full((12,) + shape, np.nan, dtype="float32")
        for mi, mm in per_month.items():
            if role in mm:
                stack[mi - 1] = mm[role]
        out[role] = stack
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
        exprs = {}
        for output in entry["outputs"]:
            lid = output["layer_id"]
            if lid in OUTPUT_EXPRS:
                exprs[lid] = OUTPUT_EXPRS[lid]
            elif "temporal_reduce" in params:
                exprs[lid] = temporal_reduce_expr(params)
            else:
                raise ConfigError(f"modis_cmg: no recipe for output {lid!r}")
        needed = {r for _, _, roles in exprs.values() for r in roles}
        missing = needed - set(params["variables"])
        if missing:
            raise ConfigError(f"modis_cmg: params.variables lacks roles {sorted(missing)}")
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

        running = {lid: RunningReduce(kind) for lid, (kind, _, _) in exprs.items()}
        for mi, month_files in sorted(by_month(files).items()):
            mm = month_mean(month_files, params)
            for lid, (_, expr, _) in exprs.items():
                running[lid].add(expr(mm))
            del mm
            log.debug("%s: month %d folded (%d files)", entry["layer_id"], mi, len(month_files))

        fp = storage.fingerprint(
            {"entry": entry, "dataset_version": source.entry["dataset_version"], "years": years}
        )
        stage_dir = Path(ctx.stage_dir)
        layers = []
        for o in entry["outputs"]:
            array = running[o["layer_id"]].result()
            if array is None:
                raise SourceError(f"{entry['source_id']}: no monthly data for {o['layer_id']}")
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
