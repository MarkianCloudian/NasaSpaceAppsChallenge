"""Refinement — mineralogy from EMIT L2B MIN v002 (plan E4, research D-010, task T051).

For an area footprint (lat, lon, radius_km) within 52°N–52°S:
  1. search EMIT granules intersecting the footprint (CMR; `emit_coverage` stops here);
  2. fetch (cached) at most `emit.max_granules_per_area` granules, least cloud first;
  3. read mineral / uncertainty NetCDF4 files with h5py, orthorectify with the GLT
     (`location/glt_x`, `location/glt_y`, 1-based; 0 = outside the scene);
  4. map `group_1/2_mineral_id` names (`mineral_metadata`) to classes with the crosswalk;
     ignore band depth below `emit.min_band_depth`; keep only detections that form connected
     clusters of >= `emit.min_cluster_pixels` pixels;
  5. class area fractions over valid pixels inside the circle -> `mineral_class_fractions`.

No granule, outside EMIT latitudes, or valid pixels covering less than
`coverage.min_coverage_fraction` of the circle -> UNKNOWN (values None), never "absent".

Source contract used (adapter `emit-l2b-min`): `search(request) -> list[granule]` where a granule is
a dict (or object) optionally carrying a `cloud` percentage and a `granule_id`; and
`fetch(request) -> FetchResult` whose directory holds the granule `.nc` files. Request:
`{"bounding_box": [w, s, e, n], "granule_ids": [...]}` (ids only when known).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from scipy import ndimage

from ..config import load_mineral_classes
from ..crosswalk import Crosswalk
from ..types import CandidateArea, GroupResult, StageContext

SOURCE_ID = "emit-l2b-min"
MAX_ABS_LAT = 52.0
EARTH_R_KM = 6371.0088
log = logging.getLogger("analogfinder.mineralogy")

UNKNOWN_VALUES: dict[str, Any] = {"mineral_class_fractions": None, "aqueous_mineral_present": None}


# --- search / fetch ---------------------------------------------------------------------------


def _bbox(footprint) -> list[float]:
    lat, lon, r = footprint
    dlat = math.degrees(r / EARTH_R_KM)
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _get(g, key, default=None):
    return g.get(key, default) if isinstance(g, Mapping) else getattr(g, key, default)


def _cloud(g) -> float:
    c = _get(g, "cloud")
    return float(c) if isinstance(c, int | float) else math.inf


def _search(ctx: StageContext, footprint) -> list:
    """Granules intersecting the footprint, least cloud first (stable)."""
    if not (-MAX_ABS_LAT <= footprint[0] <= MAX_ABS_LAT):
        return []
    src = ctx.sources.get(SOURCE_ID)
    found = list(src.search({"bounding_box": _bbox(footprint)}))
    return sorted(found, key=_cloud)


def emit_coverage(footprint, ctx: StageContext) -> bool:
    """True when at least one EMIT granule intersects the footprint (CMR search, no download)."""
    try:
        return bool(_search(ctx, footprint))
    except Exception as exc:  # network / login problems -> no coverage, never a crash
        log.warning("EMIT search failed for %s: %s", footprint, exc)
        return False


# --- reading ----------------------------------------------------------------------------------


def _mineral_names(h: h5py.File) -> dict[int, str]:
    grp = h["mineral_metadata"]
    idx = np.asarray(grp["index"][...]).ravel()
    names = [n.decode() if isinstance(n, bytes) else str(n) for n in np.asarray(grp["name"][...])]
    return {int(i): n for i, n in zip(idx, names, strict=False)}


def _read_granule(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h:
        return {
            "names": _mineral_names(h),
            "gt": [float(v) for v in np.asarray(h.attrs["geotransform"]).ravel()[:6]],
            "glt_x": np.asarray(h["location/glt_x"][...]),
            "glt_y": np.asarray(h["location/glt_y"][...]),
            "id1": np.asarray(h["group_1_mineral_id"][...]),
            "id2": np.asarray(h["group_2_mineral_id"][...]),
            "bd1": np.asarray(h["group_1_band_depth"][...], dtype=np.float32),
            "bd2": np.asarray(h["group_2_band_depth"][...], dtype=np.float32),
        }


def _ortho(raw: np.ndarray, glt_x: np.ndarray, glt_y: np.ndarray, fill) -> np.ndarray:
    """Orthorectify with the (1-based) GLT; 0 in the GLT = outside the scene -> `fill`."""
    ok = (glt_x > 0) & (glt_y > 0)
    out = np.full(glt_x.shape, fill, dtype=raw.dtype)
    out[ok] = raw[glt_y[ok] - 1, glt_x[ok] - 1]
    return out


def _granule_files(directory: Path) -> tuple[list[Path], list[Path]]:
    nc = sorted(Path(directory).rglob("*.nc"))
    unc = [p for p in nc if "UNCERT" in p.name.upper()]
    return [p for p in nc if p not in unc], unc


# --- core -------------------------------------------------------------------------------------


def _target_grid(footprint, step_lon: float, step_lat: float):
    """Pixel-centre lat/lon vectors of the footprint bbox at the EMIT ortho step."""
    w, s, e, n = _bbox(footprint)
    lons = np.arange(w, e, step_lon) + step_lon / 2
    lats = np.arange(n, s, -step_lat) - step_lat / 2
    return lats, lons


def _in_circle(footprint, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    lat0, lon0, r = footprint
    la, lo = np.meshgrid(np.radians(lats), np.radians(lons), indexing="ij")
    a = np.sin((la - math.radians(lat0)) / 2) ** 2 + (
        math.cos(math.radians(lat0)) * np.cos(la) * np.sin((lo - math.radians(lon0)) / 2) ** 2
    )
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1))) <= r


def _sample(g: dict[str, Any], lats: np.ndarray, lons: np.ndarray):
    """Ortho layers of one granule sampled (nearest) on the target grid; returns arrays + valid."""
    x0, dx, _, y0, _, dy = g["gt"]
    col = np.floor((lons - x0) / dx).astype(int)
    row = np.floor((lats - y0) / dy).astype(int)
    gx, gy = g["glt_x"], g["glt_y"]
    inside = ((row >= 0) & (row < gx.shape[0]))[:, None] & ((col >= 0) & (col < gx.shape[1]))[None]
    rr = np.clip(row, 0, gx.shape[0] - 1)[:, None]
    cc = np.clip(col, 0, gx.shape[1] - 1)[None, :]
    px, py = gx[rr, cc], gy[rr, cc]
    valid = inside & (px > 0) & (py > 0)
    px, py = np.where(valid, px, 1) - 1, np.where(valid, py, 1) - 1
    return (
        valid,
        g["id1"][py, px],
        g["id2"][py, px],
        g["bd1"][py, px],
        g["bd2"][py, px],
    )


def class_fractions(
    footprint,
    granule_files: list[Path],
    crosswalk: Crosswalk,
    *,
    min_band_depth: float,
    min_cluster_pixels: int,
) -> tuple[dict[str, float] | None, float]:
    """(class fractions over valid pixels | None when no pixel, valid fraction of the circle)."""
    classes = crosswalk.classes
    granules = [_read_granule(p) for p in granule_files]
    if not granules:
        return None, 0.0
    step_lon, step_lat = abs(granules[0]["gt"][1]), abs(granules[0]["gt"][5])
    lats, lons = _target_grid(footprint, step_lon, step_lat)
    circle = _in_circle(footprint, lats, lons)
    n_circle = int(circle.sum())
    if n_circle == 0:
        return None, 0.0

    valid = np.zeros(circle.shape, bool)
    present = {c: np.zeros(circle.shape, bool) for c in classes}
    for g in granules:  # least-cloud first: later granules only fill still-empty pixels
        v, id1, id2, bd1, bd2 = _sample(g, lats, lons)
        v &= circle & ~valid
        valid |= v
        cls_of = {i: crosswalk.emit_class(n) for i, n in g["names"].items()}
        for ids, bd in ((id1, bd1), (id2, bd2)):
            strong = v & np.isfinite(bd) & (bd >= min_band_depth)
            for i in np.unique(ids[strong]):
                c = cls_of.get(int(i))
                if c is not None:
                    present[c] |= strong & (ids == i)

    cover = int(valid.sum()) / n_circle
    n_valid = int(valid.sum())
    if n_valid == 0:
        return None, cover
    eight = np.ones((3, 3), int)
    fractions: dict[str, float] = {}
    for c in classes:
        lab, n = ndimage.label(present[c], structure=eight)
        if n:
            sizes = np.bincount(lab.ravel())[1:]
            keep = np.nonzero(sizes >= min_cluster_pixels)[0] + 1
            count = int(np.isin(lab, keep).sum())
        else:
            count = 0
        fractions[c] = count / n_valid
    return fractions, cover


def refine(area: CandidateArea, ctx: StageContext) -> GroupResult:
    """EMIT mineralogy for one scheduler-selected area (UNKNOWN when not determinable)."""
    fp = area.footprint
    emit_cfg = ctx.settings["emit"]
    min_cov = ctx.settings["coverage"]["min_coverage_fraction"]

    def unknown(reason: str, cov: float | None = None) -> GroupResult:
        log.info("area %s: EMIT mineralogy UNKNOWN (%s)", area.area_id, reason)
        return GroupResult("mineral", dict(UNKNOWN_VALUES), None, cov)

    try:
        found = _search(ctx, fp)
    except Exception as exc:
        return unknown(f"search failed: {exc}")
    if not found:
        return unknown("no EMIT granule / outside 52N-52S", 0.0)

    chosen = found[: int(emit_cfg["max_granules_per_area"])]
    request: dict[str, Any] = {"bounding_box": _bbox(fp)}
    ids = [_get(g, "granule_id") for g in chosen]
    if all(ids):
        request["granule_ids"] = ids
    try:
        res = ctx.sources.get(SOURCE_ID).fetch(request)
    except Exception as exc:
        return unknown(f"download failed: {exc}")

    mineral_files, uncert_files = _granule_files(res.path)
    mineral_files = mineral_files[: int(emit_cfg["max_granules_per_area"])]
    if not mineral_files:
        return unknown("no mineral files in fetched granules")
    log.debug(
        "area %s: %d mineral, %d uncertainty files",
        area.area_id,
        len(mineral_files),
        len(uncert_files),
    )

    cw = Crosswalk(load_mineral_classes(ctx.config_dir))
    fractions, cover = class_fractions(
        fp,
        mineral_files,
        cw,
        min_band_depth=float(emit_cfg["min_band_depth"]),
        min_cluster_pixels=int(emit_cfg["min_cluster_pixels"]),
    )
    log.info(
        "area %s: EMIT coverage %.2f of circle (%d granule file(s))",
        area.area_id,
        cover,
        len(mineral_files),
    )
    if fractions is None or cover < min_cov:
        return unknown(f"coverage {cover:.2f} < {min_cov}", cover)
    aqueous = any(f > 0 and cw.is_aqueous(c) for c, f in fractions.items())
    return GroupResult(
        "mineral",
        {"mineral_class_fractions": fractions, "aqueous_mineral_present": aqueous},
        res.source_id,
        cover,
    )
