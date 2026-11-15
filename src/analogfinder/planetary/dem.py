"""Mars terrain targets over the reference footprint (plan B4, optional FR-010, task T072).

Two modes, both over the circle of `reference_site.radius_km` around the reference site:

(a) refinement baseline (30 m): CTX DTMs from the USGS Astrogeology STAC catalogue
    (source `usgs-mars-dtm-stac`, collection from `config/sources.json`, asset `dtm`) ->
    `slope_p90` and `rms_roughness`;
(b) regional baseline (926 m): the global MOLA + HRSC blended DEM (source `mola-hrsc-blend`,
    file URL = the entry's `endpoint`) -> Horn `slope_p90` = `regional_slope` (research D-020).

Every DEM is read onto a geographic grid on the Mars sphere whose spacing equals the baseline
at the reference latitude, by area-averaging (GDAL "average" resampling): projected CTX DTMs
through a warped VRT, the geographic MOLA+HRSC file by a decimated window read. Only the window
over the footprint is read (HTTP range requests on the COG / GeoTIFF). Several CTX DTMs are
mosaicked (first valid value wins, items ordered by their overlap with the footprint box).
With a `data_dir`, the resampled window is cached atomically under
`data/cache/<source_id>/<dataset_version>/<fingerprint(request)>/` and reused without network.

Slope and roughness use the same functions as the Earth refinement (T050):
`grid.builders.dem_block_stats.horn_slope_deg` and `refine.terrain.rms_roughness_grid`, with
metre spacings from the Mars radius. Fewer than 9 valid baseline cells in the circle -> NaN.

CLI (prints the three targets with source ids, baselines and coverage):
    python -m analogfinder.planetary.dem --profile profiles/mars-rover-jezero.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds

from .. import storage
from ..grid.builders.dem_block_stats import horn_slope_deg
from ..refine.terrain import rms_roughness_grid

log = logging.getLogger("analogfinder.planetary.dem")

MARS_RADIUS_M = 3396190.0  # IAU 2015 Mars sphere, as in the CTX / MOLA+HRSC products
MARS_GEO = CRS.from_proj4(f"+proj=longlat +R={MARS_RADIUS_M:.0f} +no_defs")
MIN_CELLS = 9
DTM_ASSET = "dtm"


# --- geometry ---------------------------------------------------------------------------


def footprint_bbox(lat: float, lon: float, radius_km: float, pad_cells: float = 0.0, res=0.0):
    """(west, south, east, north) in degrees around the circle on the Mars sphere."""
    dlat = math.degrees(radius_km * 1000.0 / MARS_RADIUS_M) + pad_cells * res
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    return lon - dlon, max(lat - dlat, -90.0), lon + dlon, min(lat + dlat, 90.0)


def grid_for(lat: float, lon: float, radius_km: float, baseline_m: float):
    """Geographic target grid (transform, width, height) with ~baseline_m spacing at `lat`."""
    res_lat = math.degrees(baseline_m / MARS_RADIUS_M)
    res_lon = res_lat / max(math.cos(math.radians(lat)), 1e-6)
    w, s, e, n = footprint_bbox(lat, lon, radius_km)
    # one extra cell of halo on each side for the Horn and roughness windows
    w, e, s, n = w - res_lon, e + res_lon, s - res_lat, n + res_lat
    width, height = math.ceil((e - w) / res_lon), math.ceil((n - s) / res_lat)
    return from_origin(w, n, res_lon, res_lat), width, height


def _distance_m(lat, lon, lat0: float, lon0: float) -> np.ndarray:
    p0, p = np.radians(lat0), np.radians(lat)
    a = np.sin((p - p0) / 2) ** 2 + np.cos(p0) * np.cos(p) * np.sin(np.radians(lon - lon0) / 2) ** 2
    return 2 * MARS_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# --- reading ----------------------------------------------------------------------------


def read_on_grid(path: str, transform, width: int, height: int) -> np.ndarray:
    """DEM values (float64, NaN = no data) on the target geographic grid, area-averaged."""
    href = path if Path(path).exists() or path.startswith("/vsi") else f"/vsicurl/{path}"
    with rasterio.open(href) as src:
        if src.crs is not None and src.crs.is_geographic:
            w = transform.c
            n = transform.f
            e = w + transform.a * width
            s = n + transform.e * height
            win = from_bounds(w, s, e, n, src.transform)
            a = src.read(
                1,
                window=win,
                out_shape=(height, width),
                resampling=Resampling.average,
                masked=True,
                boundless=True,
            )
        else:
            with WarpedVRT(
                src,
                crs=MARS_GEO,
                transform=transform,
                width=width,
                height=height,
                resampling=Resampling.average,
                src_nodata=src.nodata,
            ) as vrt:
                a = vrt.read(1, masked=True)
    return np.ma.filled(a.astype("float64"), np.nan)


def mosaic(paths: Sequence[str], transform, width: int, height: int) -> np.ndarray:
    """First valid value wins, in the given order."""
    out = np.full((height, width), np.nan)
    for p in paths:
        z = read_on_grid(p, transform, width, height)
        fill = np.isnan(out) & np.isfinite(z)
        out[fill] = z[fill]
        if np.isfinite(out).all():
            break
    return out


# --- statistics -------------------------------------------------------------------------


def terrain_stats(z: np.ndarray, transform, lat0: float, lon0: float, radius_km: float):
    """slope_p90 (deg), rms_roughness (m) and coverage of the circle on a geographic grid."""
    h, w = z.shape
    lat = transform.f + transform.e * (np.arange(h) + 0.5)
    lon = transform.c + transform.a * (np.arange(w) + 0.5)
    dy = MARS_RADIUS_M * math.radians(-transform.e)
    dx_rows = MARS_RADIUS_M * np.cos(np.radians(lat)) * math.radians(transform.a)
    slope = np.full(z.shape, np.nan)
    if h >= 3:
        slope[1:-1, :] = horn_slope_deg(z, dx_rows[1:-1], dy)
    rough = rms_roughness_grid(z)
    inside = _distance_m(lat[:, None], lon[None, :], lat0, lon0) <= radius_km * 1000.0
    n_in = int(inside.sum())
    coverage = float(np.isfinite(z[inside]).sum() / n_in) if n_in else 0.0
    s = slope[inside & np.isfinite(slope)]
    r = rough[inside & np.isfinite(rough)]
    return {
        "slope_p90": float(np.percentile(s, 90)) if s.size >= MIN_CELLS else math.nan,
        "rms_roughness": float(np.median(r)) if r.size >= MIN_CELLS else math.nan,
        "coverage": round(coverage, 4),
    }


def _cached_mosaic(paths, t, w, h, cache: tuple | None) -> np.ndarray:
    """mosaic() through the download cache when `cache` = (data_dir, source_id, version)."""
    if cache is None:
        return mosaic(paths, t, w, h)
    data_dir, sid, version = cache
    request = {"dems": list(paths), "transform": list(t)[:6], "shape": [h, w]}
    d = storage.cache_dir(data_dir, sid, version or "unknown", request)
    if storage.is_complete(d):
        return np.load(d / "dem.npy")
    z = mosaic(paths, t, w, h)
    with storage.atomic_dir(d, manifest={"source_id": sid}) as tmp:
        storage.write_request(tmp, request)
        np.save(tmp / "dem.npy", z)
    return z


def regional(
    dem: str, lat: float, lon: float, radius_km: float, baseline_m: float, cache=None
) -> dict:
    """Mode (b): one global DEM (path or URL) -> regional slope p90 at `baseline_m`."""
    t, w, h = grid_for(lat, lon, radius_km, baseline_m)
    st = terrain_stats(_cached_mosaic([dem], t, w, h, cache), t, lat, lon, radius_km)
    return {"slope_p90": st["slope_p90"], "coverage": st["coverage"], "baseline_m": baseline_m}


def fine(
    dtms: Sequence[str], lat: float, lon: float, radius_km: float, baseline_m: float, cache=None
) -> dict:
    """Mode (a): local DTMs (paths or URLs, best first) -> slope p90 and RMS roughness."""
    t, w, h = grid_for(lat, lon, radius_km, baseline_m)
    st = terrain_stats(_cached_mosaic(list(dtms), t, w, h, cache), t, lat, lon, radius_km)
    return {**st, "baseline_m": baseline_m}


# --- catalogue --------------------------------------------------------------------------


def ctx_dtm_items(entry: dict, lat: float, lon: float, radius_km: float, client=None, limit=8):
    """STAC items with a `dtm` asset intersecting the footprint box, best overlap first.

    Returns [(item_id, dtm_href, overlap_fraction_of_box)].
    """
    if client is None:
        from pystac_client import Client

        client = Client.open(entry["endpoint"])
    w, s, e, n = footprint_bbox(lat, lon, radius_km)
    found = []
    for it in client.search(collections=[entry["collection"]], bbox=[w, s, e, n]).items():
        if DTM_ASSET not in it.assets:
            continue
        bw, bs, be, bn = it.bbox
        ow, oe, os_, on = max(w, bw), min(e, be), max(s, bs), min(n, bn)
        frac = max(oe - ow, 0) * max(on - os_, 0) / ((e - w) * (n - s))
        found.append((it.id, it.assets[DTM_ASSET].href, round(frac, 4)))
    found.sort(key=lambda x: (-x[2], x[0]))
    return found[:limit]


# --- profile-driven extraction ----------------------------------------------------------


def _target_source(c: dict) -> str | None:
    for t in (c.get("sources") or {}).get("target", []):
        return t.get("source_id")
    return None


def extract(profile: dict, sources: dict, client=None, data_dir=None) -> list[dict[str, Any]]:
    """Proposed Mars targets for the profile's DEM criteria (slope_p90 / rms_roughness)."""
    site = profile["reference_site"]
    lat, lon, r = float(site["lat"]), float(site["lon"]), float(site["radius_km"])
    entries = {e["source_id"]: e for e in sources["sources"]}
    out: list[dict[str, Any]] = []
    fine_cache: dict[float, dict] = {}
    for c in profile["criteria"]:
        q = c.get("quantity")
        if q not in ("slope_p90", "rms_roughness") or c.get("comparison") == "not_comparable":
            continue
        sid, base = _target_source(c), float(c["baseline_m"])
        entry = entries.get(sid)
        if entry is None:
            out.append({"criterion": c["id"], "error": f"unknown target source {sid!r}"})
            continue
        if c.get("evaluation_scale") == "refinement":
            if base not in fine_cache:
                items = ctx_dtm_items(entry, lat, lon, r, client=client)
                cache = (data_dir, sid, entry.get("dataset_version")) if data_dir else None
                hrefs = [h for _, h, _ in items]
                res = fine(hrefs, lat, lon, r, base, cache) if items else None
                fine_cache[base] = {"res": res, "items": [i for i, _, _ in items]}
            got = fine_cache[base]
            if got["res"] is None:
                out.append(
                    {"criterion": c["id"], "error": "no DTM in the catalogue covers the site"}
                )
                continue
            value, extra = (
                got["res"][q],
                {"coverage": got["res"]["coverage"], "items": got["items"]},
            )
        else:
            cache = (data_dir, sid, entry.get("dataset_version")) if data_dir else None
            res = regional(entry["endpoint"], lat, lon, r, base, cache)
            value, extra = res["slope_p90"], {"coverage": res["coverage"]}
        out.append(
            {
                "criterion": c["id"],
                "quantity": q,
                "value": value,
                "unit": c.get("unit"),
                "baseline_m": base,
                "source_id": sid,
                "dataset_version": entry.get("dataset_version"),
                **extra,
            }
        )
    return out


def main(argv=None) -> int:
    from ..config import load_sources

    ap = argparse.ArgumentParser(description="Mars DEM targets over the reference footprint")
    ap.add_argument("--profile", default="profiles/mars-rover-jezero.json")
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--data-dir", default="data")
    a = ap.parse_args(argv)
    profile = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    for row in extract(profile, load_sources(a.config_dir), data_dir=a.data_dir):
        if "error" in row:
            print(f"{row['criterion']}: {row['error']}")
            continue
        extra = f"items {', '.join(row['items'])}" if "items" in row else ""
        print(
            f"{row['criterion']}: {row['quantity']} = {row['value']:.3f} {row['unit']} "
            f"@ {row['baseline_m']:g} m baseline | source {row['source_id']} | "
            f"coverage {row['coverage']:.2f} {extra}".rstrip()
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
