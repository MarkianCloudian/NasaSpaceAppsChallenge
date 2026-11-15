"""Mars target extraction: mineral class fractions from CRISM MTRDR summary products
(plan B4, optional FR-010, task T072).

  1. query PDS ODE REST for CRISM MTRDR observations intersecting the reference footprint;
  2. download only the `_su*_mtr3` summary-parameter files (.img + .hdr + .lbl, ~80 MB),
     never the full I/F cubes;
  3. read with rasterio (GDAL ENVI driver), band names from the .hdr `band names` field;
  4. threshold parameters with `crism_rules` from config/mineral_classes.json; 65535 = no data;
  5. class area fractions over valid pixels inside the footprint circle.

Usage (prints class fractions with observation ids):
    python -m analogfinder.planetary.crism --lat 18.4 --lon 77.5 --radius-km 20 \
        [--files a.img b.img]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform

from ..config import load_mineral_classes

MARS_R_KM = 3396.19
NODATA = 65535.0
ODE_URL = "https://oderest.rsl.wustl.edu/live2/"


# --- reading ----------------------------------------------------------------------------


def hdr_band_names(img_path) -> list[str]:
    hdr = Path(img_path).with_suffix(".hdr")
    text = hdr.read_text(errors="replace")
    m = re.search(r"band names\s*=\s*\{(.*?)\}", text, re.S | re.I)
    if not m:
        raise ValueError(f"{hdr.name}: no 'band names' field")
    return [b.strip() for b in m.group(1).split(",") if b.strip()]


def _mars_lonlat(ds):
    """Longitude/latitude (deg, Mars sphere) of every pixel centre."""
    rows, cols = np.mgrid[0 : ds.height, 0 : ds.width]
    xs, ys = rasterio.transform.xy(ds.transform, rows.ravel(), cols.ravel())
    geo = CRS.from_proj4(f"+proj=longlat +R={MARS_R_KM * 1000:.0f} +no_defs")
    lon, lat = transform(ds.crs, geo, list(xs), list(ys))
    return np.asarray(lon).reshape(ds.shape), np.asarray(lat).reshape(ds.shape)


def _haversine_km(lat0, lon0, lat, lon):
    p0, p = np.radians(lat0), np.radians(lat)
    a = np.sin((p - p0) / 2) ** 2 + np.cos(p0) * np.cos(p) * np.sin(np.radians(lon - lon0) / 2) ** 2
    return 2 * MARS_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def observation_counts(img_path, rules, footprint=None):
    """Valid-pixel and per-class pixel counts for one summary-parameter file."""
    names = hdr_band_names(img_path)
    with rasterio.open(img_path) as ds:
        if ds.count != len(names):
            raise ValueError(f"{Path(img_path).name}: {ds.count} bands but {len(names)} band names")
        needed = sorted({r["parameter"] for r in rules})
        missing = [p for p in needed if p not in names]
        if missing:
            raise ValueError(f"{Path(img_path).name}: parameters not in file: {missing}")
        arrays = {}
        for p in needed:
            a = ds.read(names.index(p) + 1).astype("float64")
            a[(a == NODATA) | ~np.isfinite(a)] = np.nan
            arrays[p] = a
        inside = np.ones(ds.shape, bool)
        if footprint:
            lon, lat = _mars_lonlat(ds)
            inside = (
                _haversine_km(footprint["lat"], footprint["lon"], lat, lon)
                <= footprint["radius_km"]
            )
        res_m = abs(ds.transform.a)
    valid = inside & np.any([np.isfinite(a) for a in arrays.values()], axis=0)
    counts = {}
    for r in rules:
        a = arrays[r["parameter"]]
        hit = valid & np.isfinite(a) & (a >= r["threshold"])
        counts[r["class"]] = counts.get(r["class"], 0) + int(hit.sum())
    return {
        "observation_id": observation_id(img_path),
        "valid_pixels": int(valid.sum()),
        "class_pixels": counts,
        "pixel_size_m": res_m,
    }


def observation_id(path) -> str:
    m = re.match(r"([a-z]{3}[0-9a-f]{8})", Path(path).name.lower())
    return m.group(1).upper() if m else Path(path).stem


def class_fractions(img_paths, mineral_classes, footprint=None):
    """Pooled class fractions over all observations (+ per-observation detail)."""
    rules = mineral_classes["crism_rules"]
    per_obs = [observation_counts(p, rules, footprint) for p in img_paths]
    total = sum(o["valid_pixels"] for o in per_obs)
    classes = sorted({r["class"] for r in rules})
    pooled = {
        c: (sum(o["class_pixels"].get(c, 0) for o in per_obs) / total if total else None)
        for c in classes
    }
    for o in per_obs:
        v = o["valid_pixels"]
        o["fractions"] = {
            c: round(o["class_pixels"].get(c, 0) / v, 6) if v else None for c in classes
        }
    return {
        "state": "KNOWN" if total else "UNKNOWN",
        "mineral_class_fractions": {
            c: (round(v, 6) if v is not None else None) for c, v in pooled.items()
        },
        "valid_pixels": total,
        "observations": [
            {k: o[k] for k in ("observation_id", "valid_pixels", "fractions", "pixel_size_m")}
            for o in per_obs
        ],
        "thresholds": {
            r["class"]: {
                "parameter": r["parameter"],
                "threshold": r["threshold"],
                "status": r.get("status", ""),
            }
            for r in rules
        },
        "source": "CRISM MTRDR summary parameters (PDS Geosciences Node via ODE REST)",
        "value_status": "measured" if total else "placeholder",
    }


# --- ODE search and download ------------------------------------------------------------


def ode_search(footprint, timeout=60):
    """MTRDR observations intersecting the footprint bbox -> [{observation_id, files: [url]}]."""
    import requests

    lat, lon, r = footprint["lat"], footprint["lon"], footprint["radius_km"]
    dlat = math.degrees(r / MARS_R_KM)
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    lon360 = lon % 360
    params = {
        "query": "product",
        "target": "mars",
        "ihid": "MRO",
        "iid": "CRISM",
        "pt": "MTRDR",
        "minlat": lat - dlat,
        "maxlat": lat + dlat,
        "westernlon": (lon360 - dlon) % 360,
        "easternlon": (lon360 + dlon) % 360,
        "results": "f",
        "output": "JSON",
        "limit": 100,
    }
    resp = requests.get(ODE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    products = resp.json().get("ODEResults", {}).get("Products", {}) or {}
    items = products.get("Product", [])
    items = [items] if isinstance(items, dict) else items
    out = {}
    for p in items:
        files = (p.get("Product_files") or {}).get("Product_file", [])
        files = [files] if isinstance(files, dict) else files
        urls = [
            f["URL"]
            for f in files
            if re.search(r"_su\w*_mtr3\.(img|hdr|lbl)$", f.get("FileName", ""), re.I)
        ]
        if urls:
            oid = observation_id(Path(urls[0]).name)
            out.setdefault(oid, set()).update(urls)
    return [{"observation_id": k, "files": sorted(v)} for k, v in sorted(out.items())]


def download(observations, cache_dir, timeout=120):
    import requests

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    imgs = []
    for o in observations:
        for url in o["files"]:
            dst = cache / Path(url).name.lower()
            if not dst.exists():
                tmp = dst.with_name(dst.name + ".partial-dl")
                with requests.get(url, stream=True, timeout=timeout) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                tmp.rename(dst)
            if dst.suffix == ".img":
                imgs.append(dst)
    return imgs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True, help="east longitude, -180..180 or 0..360")
    ap.add_argument("--radius-km", type=float, default=20.0)
    ap.add_argument("--files", nargs="*", help="local _su*_mtr3.img files (skip ODE search)")
    ap.add_argument("--cache-dir", default="data/cache/crism-mtrdr-ode/manual")
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--max-observations", type=int, default=5)
    a = ap.parse_args(argv)
    fp = {"lat": a.lat, "lon": a.lon, "radius_km": a.radius_km}
    mc = load_mineral_classes(a.config_dir)
    if a.files:
        imgs = [Path(f) for f in a.files]
    else:
        obs = ode_search(fp)[: a.max_observations]
        print(f"ODE: {len(obs)} MTRDR observation(s) with summary files", file=sys.stderr)
        imgs = download(obs, a.cache_dir)
    res = class_fractions(imgs, mc, fp)
    res["footprint"] = fp
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
