"""Refinement: EMIT L2B mineralogy over a candidate footprint (plan E4, research D-010, T050).

Per footprint {lat, lon, radius_km}:
  1. outside 52°N–52°S -> UNKNOWN (no EMIT coverage);
  2. search EMIT L2B MIN granules intersecting the footprint bbox, download (cached, at most
     `emit.max_granules_per_area`, least cloud first);
  3. read each granule with h5py, orthorectify with the GLT, map group_1/group_2 mineral ids
     through `mineral_metadata` names and the crosswalk to classes, ignore band depth below
     `emit.min_band_depth`;
  4. union all granules on one lat/lon grid clipped to the circle; drop detections smaller than
     `emit.min_cluster_pixels` connected pixels (8-connectivity);
  5. coverage = valid pixels / pixels in circle; below `coverage.min_coverage_fraction` -> UNKNOWN;
  6. class fractions over valid pixels; aqueous_mineral_present = any aqueous-group class present.
     A pixel can carry one group-1 class (Fe minerals, ~1 um) and one group-2 class (~2 um),
     so fractions are per class and need not sum to 1.
No granule or no coverage is UNKNOWN, never "absent" (constitution IV).

The uncertainty files (EMIT L2B MINUNCERT) are downloaded with the granule but not used yet.
Ported from the hackathon pipeline (src/emit_l2b.py: GLT logic as in NASA emit_tools).
"""
import math
from pathlib import Path

import h5py
import numpy as np
from scipy import ndimage

from ..crosswalk import Crosswalk

EMIT_LAT_LIMIT = 52.0
EARTH_R_KM = 6371.0
FILL = -9999


def footprint_bbox(lat, lon, radius_km):
    dlat = math.degrees(radius_km / EARTH_R_KM)
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _haversine_km(lat0, lon0, lat, lon):
    p0, p = np.radians(lat0), np.radians(lat)
    a = (np.sin((p - p0) / 2) ** 2
         + np.cos(p0) * np.cos(p) * np.sin(np.radians(lon - lon0) / 2) ** 2)
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def unknown(reason, **extra):
    return {"state": "UNKNOWN", "reason": reason, "mineral_class_fractions": None,
            "aqueous_mineral_present": None, **extra}


# --- granule reading --------------------------------------------------------------------

def _decode(arr):
    return [x.decode() if isinstance(x, bytes) else str(x) for x in arr]


def class_lookup(names, indices, xwalk: Crosswalk):
    """mineral_metadata index -> class id (or None)."""
    return {int(i): xwalk.emit_class(n) for i, n in zip(indices, names)}


def read_granule(path, xwalk: Crosswalk, min_band_depth: float):
    """Orthorectified per-class boolean masks + valid mask + geotransform for one granule."""
    with h5py.File(path, "r") as h:
        gt = [float(v) for v in h.attrs["geotransform"]]
        glt_x = h["location/glt_x"][:].astype(np.int64)
        glt_y = h["location/glt_y"][:].astype(np.int64)
        mm = h["mineral_metadata"]
        lut = class_lookup(_decode(mm["name"][:]), mm["index"][:], xwalk)
        ok = (glt_x != 0) & (glt_y != 0)
        rows, cols = glt_y[ok] - 1, glt_x[ok] - 1
        valid = np.zeros(glt_x.shape, bool)
        masks = {c: np.zeros(glt_x.shape, bool) for c in xwalk.classes}
        for g in (1, 2):
            ids = h[f"group_{g}_mineral_id"][:][rows, cols].astype(np.int64)
            bd = h[f"group_{g}_band_depth"][:][rows, cols].astype(np.float32)
            inscene = ids != FILL
            v = np.zeros(glt_x.shape, bool)
            v[ok] = inscene
            valid |= v
            strong = inscene & (bd >= min_band_depth)
            for idx in np.unique(ids[strong]):
                cls = lut.get(int(idx))
                if cls is None:
                    continue
                m = np.zeros(glt_x.shape, bool)
                m[ok] = strong & (ids == idx)
                masks[cls] |= m
    return {"gt": gt, "valid": valid, "masks": masks}


# --- footprint aggregation --------------------------------------------------------------

def footprint_fractions(granules, footprint, xwalk: Crosswalk, min_cluster_pixels: int):
    """Union granules on a common grid over the footprint circle; return counts and fractions."""
    lat0, lon0, r = footprint["lat"], footprint["lon"], footprint["radius_km"]
    west, south, east, north = footprint_bbox(lat0, lon0, r)
    step = min(abs(g["gt"][1]) for g in granules)  # finest granule pixel (deg)
    nx = int(math.ceil((east - west) / step))
    ny = int(math.ceil((north - south) / step))
    lons = west + (np.arange(nx) + 0.5) * step
    lats = north - (np.arange(ny) + 0.5) * step
    in_circle = _haversine_km(lat0, lon0, lats[:, None], lons[None, :]) <= r
    valid = np.zeros((ny, nx), bool)
    masks = {c: np.zeros((ny, nx), bool) for c in xwalk.classes}
    for g in granules:
        gx0, gdx, _, gy0, _, gdy = g["gt"]
        # granule pixel index for each target cell centre (nearest)
        ci = np.floor((lons - gx0) / gdx).astype(np.int64)
        ri = np.floor((lats - gy0) / gdy).astype(np.int64)
        gh, gw = g["valid"].shape
        cok, rok = (ci >= 0) & (ci < gw), (ri >= 0) & (ri < gh)
        if not cok.any() or not rok.any():
            continue
        sub = np.ix_(np.where(rok)[0], np.where(cok)[0])
        take = np.ix_(ri[rok], ci[cok])
        valid[sub] |= g["valid"][take]
        for c in xwalk.classes:
            masks[c][sub] |= g["masks"][c][take]
    valid &= in_circle
    n_circle, n_valid = int(in_circle.sum()), int(valid.sum())
    counts = {}
    for c, m in masks.items():
        m &= valid
        if min_cluster_pixels > 1 and m.any():
            lab, n = ndimage.label(m, structure=np.ones((3, 3), int))
            sizes = np.bincount(lab.ravel())
            keep = sizes >= min_cluster_pixels
            keep[0] = False
            m = keep[lab]
        counts[c] = int(m.sum())
    return {"pixel_deg": step, "pixels_in_circle": n_circle, "valid_pixels": n_valid,
            "class_pixels": counts}


def summarise(agg, xwalk: Crosswalk, min_coverage: float, **provenance):
    cov = agg["valid_pixels"] / agg["pixels_in_circle"] if agg["pixels_in_circle"] else 0.0
    base = {"coverage_fraction": round(cov, 4), "pixel_size_m": round(agg["pixel_deg"] * 111320, 1),
            **provenance}
    if cov < min_coverage:
        return unknown(f"EMIT coverage {cov:.2f} below {min_coverage}", **base)
    fr = {c: round(n / agg["valid_pixels"], 6) for c, n in agg["class_pixels"].items()}
    return {"state": "KNOWN", "mineral_class_fractions": fr,
            "aqueous_mineral_present": any(v > 0 and xwalk.is_aqueous(c) for c, v in fr.items()),
            **base}


# --- entry points used by the refinement scheduler (T051) -------------------------------

def emit_coverage(footprint, source) -> int:
    """Number of EMIT granules intersecting the footprint (CMR search only, no download)."""
    if abs(footprint["lat"]) > EMIT_LAT_LIMIT:
        return 0
    req = {"bounding_box": footprint_bbox(footprint["lat"], footprint["lon"], footprint["radius_km"])}
    return len(source.search(req))


def granule_files(directory):
    return sorted(p for p in Path(directory).rglob("EMIT_L2B_MIN_*.nc") if "UNCERT" not in p.name)


def refine_area(footprint, source, settings, mineral_classes):
    """Mineralogy result for one footprint. `source` = EarthdataSource for EMIT L2B MIN."""
    if abs(footprint["lat"]) > EMIT_LAT_LIMIT:
        return unknown("outside EMIT coverage (52°N–52°S)", source_id=source.source_id)
    emit = settings["emit"]
    request = {"bounding_box": [round(v, 5) for v in footprint_bbox(
                   footprint["lat"], footprint["lon"], footprint["radius_km"])],
               "max_granules": emit["max_granules_per_area"], "least_cloud": True}
    from ..sources.base import EmptyResult
    try:
        directory = source.fetch(request)
    except EmptyResult:
        return unknown("no EMIT granule intersects the footprint", source_id=source.source_id)
    return refine_from_files(granule_files(directory), footprint, settings, mineral_classes,
                             source_id=source.source_id)


def refine_from_files(files, footprint, settings, mineral_classes, source_id="emit-l2b-min"):
    """Same as refine_area for already downloaded granules (offline use and tests)."""
    xwalk = Crosswalk(mineral_classes)
    emit, cov = settings["emit"], settings["coverage"]
    if not files:
        return unknown("no EMIT granule intersects the footprint", source_id=source_id)
    granules = [read_granule(f, xwalk, emit["min_band_depth"]) for f in files]
    agg = footprint_fractions(granules, footprint, xwalk, emit["min_cluster_pixels"])
    return summarise(agg, xwalk, cov["min_coverage_fraction"], source_id=source_id,
                     granules=[Path(f).stem for f in files], footprint=footprint)
