"""Builder type `gridded_netcdf` (plan C4, research D-008 / D-019, task T043).

Fallback for the `power_climate` entry (ERA5 monthly means via the Copernicus CDS). The registry
`fallback` block carries only `builder`, `source_id` and `params`; `grid/build.py` must pass an
entry that also has the primary entry's `layer_id`, `outputs` and `resampling`, so that exactly
the primary outputs are written. The manifest layers name the fallback `source_id` (`era5-cds`).

Steps:
1. One `cdsapi` request for all variables and all reference years (global, NetCDF4), cached under
   the source's cache directory (a second build makes no request).
2. Read with h5py (no netCDF4 dependency), apply `scale_factor` / `add_offset` / fill values.
3. Reduce to a 12-month climatology per variable (mean over the reference years), convert units,
   evaluate `params.derived` (`magnus(t2m, d2m)`, `hypot(u10, v10)`) on the monthly fields.
4. Per output: annual mean / min / max of the monthly means, or annual total (monthly daily-mean
   × days in month). Longitude 0–360° is wrapped to −180…180 (with a wrap-around pad so the
   antimeridian interpolates correctly), descending latitude is flipped.
5. Bilinear resampling to the 0.05° grid and one GeoTIFF per output.

Output recipes default to `DEFAULT_RECIPES` (keyed by output `layer_id`) and can be overridden
or extended in `params.recipes`: `{layer_id: {"expr": "t2m", "stat": "mean|min|max|total"}}`.

Verify (recorded in research.md, not asserted here): NetCDF variable/dimension names written by
the current CDS for `reanalysis-era5-single-levels-monthly-means` (short names `t2m d2m tp u10
v10 ssrd`, time dimension `valid_time` or `time`), and that monthly-mean `tp`/`ssrd` are daily
means per month (m/day, J/m²/day).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from ... import storage
from ...errors import ConfigError, SourceError
from .. import cells
from .climatology_rest import bilinear_to_grid
from .modis_cmg import resolve_years

log = logging.getLogger("analogfinder.grid.builders.gridded_netcdf")

DATASET_FILE = "era5_monthly.nc"
DAYS_IN_MONTH = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], dtype="float64")
MAGNUS_A, MAGNUS_B = 17.625, 243.04  # Alduchov & Eskridge (1996), °C

# CDS variable name -> (NetCDF short name, factor, offset); physical = raw * factor + offset.
VARIABLES: dict[str, tuple[str, float, float]] = {
    "2m_temperature": ("t2m", 1.0, -273.15),  # K -> degC
    "2m_dewpoint_temperature": ("d2m", 1.0, -273.15),  # K -> degC
    "total_precipitation": ("tp", 1000.0, 0.0),  # m/day -> mm/day
    "10m_u_component_of_wind": ("u10", 1.0, 0.0),
    "10m_v_component_of_wind": ("v10", 1.0, 0.0),
    "surface_solar_radiation_downwards": ("ssrd", 1.0 / 3.6e6, 0.0),  # J/m2/day -> kWh/m2/day
}

DEFAULT_RECIPES: dict[str, dict[str, str]] = {
    "t2m_mean": {"expr": "t2m", "stat": "mean"},
    "t2m_min": {"expr": "t2m", "stat": "min"},
    "t2m_max": {"expr": "t2m", "stat": "max"},
    "rh2m_mean": {"expr": "rh2m_mean", "stat": "mean"},
    "ws10m_mean": {"expr": "ws10m_mean", "stat": "mean"},
    "precip_annual": {"expr": "tp", "stat": "total"},
    "insolation_mean": {"expr": "ssrd", "stat": "mean"},
}


# ----------------------------------------------------------------------------- numerics


def magnus_rh(t_c: np.ndarray, td_c: np.ndarray) -> np.ndarray:
    """Relative humidity (%) from air and dewpoint temperature (°C), Magnus formula."""
    rh = 100.0 * np.exp(MAGNUS_A * td_c / (MAGNUS_B + td_c) - MAGNUS_A * t_c / (MAGNUS_B + t_c))
    return np.clip(rh, 0.0, 100.0)


def _call(expr: str) -> tuple[str, list[str]]:
    expr = expr.strip()
    if "(" not in expr or not expr.endswith(")"):
        raise ConfigError(f"gridded_netcdf: bad derived expression {expr!r}")
    name, rest = expr[:-1].split("(", 1)
    return name.strip(), [a.strip() for a in rest.split(",")]


def evaluate_derived(expr: str, monthly: dict[str, np.ndarray]) -> np.ndarray:
    """Evaluate `magnus(t, td)` or `hypot(u, v)` on monthly fields (names from `monthly`)."""
    name, args = _call(expr)
    for a in args:
        if a not in monthly:
            raise ConfigError(f"gridded_netcdf: {expr!r} needs variable {a!r}")
    if name == "magnus" and len(args) == 2:
        return magnus_rh(monthly[args[0]], monthly[args[1]])
    if name == "hypot" and len(args) == 2:
        return np.hypot(monthly[args[0]], monthly[args[1]])
    raise ConfigError(f"gridded_netcdf: unknown derived function in {expr!r}")


def annual_statistic(monthly: np.ndarray, stat: str) -> np.ndarray:
    """Reduce a (12, lat, lon) monthly climatology; `total` = Σ monthly daily-mean × days."""
    if stat == "mean":
        return monthly.mean(axis=0)
    if stat == "min":
        return monthly.min(axis=0)
    if stat == "max":
        return monthly.max(axis=0)
    if stat == "total":
        return (monthly * DAYS_IN_MONTH[:, None, None]).sum(axis=0)
    raise ConfigError(f"gridded_netcdf: unknown statistic {stat!r}")


def normalise_grid(
    lat: np.ndarray, lon: np.ndarray, data: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (lat ascending, lon ascending −180…180 padded one column each side, data).

    `data` has shape (..., lat, lon). Longitudes in 0–360° are wrapped; the pad columns repeat
    the opposite edge (±360°) so interpolation across the antimeridian works.
    """
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    if lat[0] > lat[-1]:
        lat = lat[::-1]
        data = data[..., ::-1, :]
    lon = np.where(lon >= 180.0, lon - 360.0, lon)
    order = np.argsort(lon, kind="stable")
    lon, data = lon[order], data[..., order]
    lon = np.concatenate([[lon[-1] - 360.0], lon, [lon[0] + 360.0]])
    data = np.concatenate([data[..., -1:], data, data[..., :1]], axis=-1)
    return lat, lon, data


# ----------------------------------------------------------------------------- file reading


def _decode(ds, raw: np.ndarray) -> np.ndarray:
    a = ds.attrs
    out = raw.astype("float64")
    bad = np.zeros(out.shape, dtype=bool)
    for key in ("_FillValue", "missing_value"):
        if key in a:
            bad |= raw == np.asarray(a[key]).reshape(-1)[0]
    if "scale_factor" in a:
        out *= float(np.asarray(a["scale_factor"]).reshape(-1)[0])
    if "add_offset" in a:
        out += float(np.asarray(a["add_offset"]).reshape(-1)[0])
    out[bad] = np.nan
    return out


def _first_dataset(f, names: tuple[str, ...]):
    for n in names:
        if n in f:
            return f[n]
    raise SourceError(f"gridded_netcdf: none of {names} found in {Path(f.filename).name}")


def read_monthly_climatology(
    path: Path, short_names: list[str]
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Read ERA5 monthly means: returns (lat, lon, {short_name: (12, lat, lon) float64}), the
    mean over all years per calendar month. Time steps are assumed chronological, 12 per year."""
    import h5py

    out: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as f:
        lat = np.asarray(_first_dataset(f, ("latitude", "lat"))[...], dtype="float64")
        lon = np.asarray(_first_dataset(f, ("longitude", "lon"))[...], dtype="float64")
        time_ds = _first_dataset(f, ("valid_time", "time"))
        order = np.argsort(np.asarray(time_ds[...]), kind="stable")
        nt = len(order)
        if nt % 12:
            raise SourceError(f"gridded_netcdf: {nt} time steps is not a whole number of years")
        for name in short_names:
            if name not in f:
                raise SourceError(f"gridded_netcdf: variable {name!r} missing in {path.name}")
            ds = f[name]
            if ds.shape[0] != nt or ds.shape[1:] != (len(lat), len(lon)):
                raise SourceError(f"gridded_netcdf: {name} shape {ds.shape} unexpected")
            raw = np.asarray(ds[...])[order]
            vals = _decode(ds, raw).reshape(nt // 12, 12, len(lat), len(lon))
            out[name] = np.nanmean(vals, axis=0)
    return lat, lon, out


# ----------------------------------------------------------------------------- download


def build_request(variables: list[str], years: list[int]) -> dict:
    """The single CDS request for all variables and reference years (global, NetCDF4)."""
    return {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": list(variables),
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def _cds_client():
    import cdsapi

    return cdsapi.Client()  # credentials from ~/.cdsapirc, never from the repository


def fetch_era5(source, request: dict, client_factory=_cds_client) -> Path:
    """Download (or reuse from cache) the NetCDF file for `request`; returns its path."""
    final = source.cache_path(request)
    if not storage.is_complete(final):
        source.limiter.acquire()
        try:
            with storage.atomic_dir(
                final,
                manifest={
                    "source_id": source.source_id,
                    "dataset_version": source.entry["dataset_version"],
                },
            ) as tmp:
                storage.write_request(tmp, request)
                client_factory().retrieve(source.entry["dataset"], request, str(tmp / DATASET_FILE))
        except Exception as exc:  # cdsapi raises plain Exception subclasses
            raise SourceError(f"{source.source_id}: CDS request failed: {exc}") from exc
    path = final / DATASET_FILE
    if not path.is_file():
        raise SourceError(f"{source.source_id}: {DATASET_FILE} missing in {final}")
    return path


# ----------------------------------------------------------------------------- builder


class GriddedNetcdfBuilder:
    """`Builder.build(entry, ctx) -> list[dict]` (manifest layer entries); files go to
    `ctx.stage_dir`. `client_factory` is injectable for tests."""

    def __init__(self, client_factory=_cds_client):
        self.client_factory = client_factory

    def build(self, entry: dict, ctx) -> list[dict]:
        t0 = time.monotonic()
        params = entry["params"]
        outputs = entry.get("outputs") or []
        if not outputs:
            raise ConfigError("gridded_netcdf: entry has no outputs (merge the primary entry's)")
        variables = list(params.get("variables") or [])
        unknown = [v for v in variables if v not in VARIABLES]
        if not variables or unknown:
            raise ConfigError(f"gridded_netcdf: unsupported/empty variables {unknown or variables}")
        derived: dict[str, str] = params.get("derived") or {}
        recipes = {**DEFAULT_RECIPES, **(params.get("recipes") or {})}
        for o in outputs:
            if o["layer_id"] not in recipes:
                raise ConfigError(f"gridded_netcdf: no recipe for output {o['layer_id']!r}")

        years = resolve_years(params, ctx.settings)
        source = ctx.sources.get(entry["source_id"])
        request = build_request(variables, years)
        path = fetch_era5(source, request, self.client_factory)

        shorts = [VARIABLES[v][0] for v in variables]
        lat, lon, raw = read_monthly_climatology(path, shorts)
        monthly = {
            VARIABLES[v][0]: raw[VARIABLES[v][0]] * VARIABLES[v][1] + VARIABLES[v][2]
            for v in variables
        }
        for name, expr in derived.items():
            monthly[name] = evaluate_derived(expr, monthly)

        lat_t, lon_t = cells.cell_centres()
        fp = storage.fingerprint(
            {"entry": entry, "dataset_version": source.entry["dataset_version"], "years": years}
        )
        stage_dir = Path(ctx.stage_dir)
        layers = []
        for o in outputs:
            recipe = recipes[o["layer_id"]]
            if recipe["expr"] not in monthly:
                raise ConfigError(
                    f"gridded_netcdf: output {o['layer_id']!r} needs {recipe['expr']!r}, "
                    "not provided by params.variables / params.derived"
                )
            annual = annual_statistic(monthly[recipe["expr"]], recipe["stat"])
            lat_ax, lon_ax, native = normalise_grid(lat, lon, annual)
            array = bilinear_to_grid(lat_ax, lon_ax, native, lat_t, lon_t)
            name = f"{o['layer_id']}.tif"
            cells.write_layer(stage_dir / name, array)
            layer = {
                "layer_id": o["layer_id"],
                "quantity": o["quantity"],
                "unit": o["unit"],
                "statistic": o["statistic"],
                "source_id": entry["source_id"],  # the fallback source, recorded in the manifest
                "dataset_version": source.entry["dataset_version"],
                "reference_period": f"{years[0]}-{years[-1]}",
                "resampling": entry.get("resampling", "bilinear"),
                "file": name,
                "fingerprint": fp,
                "nodata": None,
            }
            if "baseline_m" in o:
                layer["baseline_m"] = o["baseline_m"]
            layers.append(layer)
        log.info("%s (ERA5 fallback) built in %.1f s", entry.get("layer_id"), time.monotonic() - t0)
        return layers
