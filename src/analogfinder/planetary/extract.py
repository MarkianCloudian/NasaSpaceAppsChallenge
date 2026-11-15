"""Propose Mars profile targets from planetary data (task T074, plan B4, FR-010).

`propose(profile, sources, mineral_classes, ...)` returns, per requested criterion, the value
measured over the reference footprint, a proposed `target` and a `sources.target` entry
(source id, dataset version, access date, citation) ready to paste into the profile. The
profile file is never modified.

- `traverse_slope`, `roughness`, `regional_slope` (quantities `slope_p90`, `rms_roughness`):
  measured by `planetary.dem` (T072). Proposed target = a point target at the Mars value
  (`min = max = value`); the criterion's tolerance then scores Earth deviations. Widening it to
  a band is a profile-author decision (T036) and is not made here; the current target is shown.
- `mineral_classes` (`mineral_class_fractions`): CRISM MTRDR class fractions (T073); proposed
  `classes` = classes with fraction >= `min_class_fraction` (default 0.001 of valid pixels),
  largest first. `aqueous_minerals`: `value` = any of those classes is in an aqueous group.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from .. import storage
from ..crosswalk import Crosswalk
from . import crism, dem

DEM_QUANTITIES = ("slope_p90", "rms_roughness")
MINERAL_QUANTITIES = ("mineral_class_fractions", "aqueous_mineral_present")


def _entry(sources: dict, sid: str) -> dict:
    for e in sources["sources"]:
        if e["source_id"] == sid:
            return e
    return {"source_id": sid}


def _source_entry(entry: dict, today: str, citation: str) -> dict:
    return {
        "source_id": entry["source_id"],
        "version": str(entry.get("dataset_version", "unknown")),
        "accessed": today,
        "citation": citation,
    }


def _crism_fractions(profile, sources, mineral_classes, data_dir, max_obs, ode=None):
    site = profile["reference_site"]
    fp = {"lat": site["lat"], "lon": site["lon"], "radius_km": site["radius_km"]}
    search = ode or crism.ode_search
    obs = search(fp)[:max_obs]
    if not obs:
        return None, []
    entry = _entry(sources, "crism-mtrdr-ode")
    request = {"footprint": fp, "observations": [o["observation_id"] for o in obs]}
    cache = storage.cache_dir(
        data_dir, entry["source_id"], str(entry.get("dataset_version")), request
    )
    imgs = crism.download(obs, cache)
    return crism.class_fractions(imgs, mineral_classes, fp), [o["observation_id"] for o in obs]


def propose(
    profile: dict,
    sources: dict,
    mineral_classes: dict,
    criteria: list[str] | None = None,
    data_dir="data",
    today: str | None = None,
    min_class_fraction: float = 0.001,
    max_crism_obs: int = 3,
    stac_client=None,
    ode=None,
) -> list[dict[str, Any]]:
    today = today or dt.date.today().isoformat()
    wanted = [
        c
        for c in profile["criteria"]
        if c.get("comparison") != "not_comparable"
        and c.get("quantity") in DEM_QUANTITIES + MINERAL_QUANTITIES
        and (criteria is None or c["id"] in criteria)
    ]
    out: list[dict[str, Any]] = []
    if any(c["quantity"] in DEM_QUANTITIES for c in wanted):
        rows = {r["criterion"]: r for r in dem.extract(profile, sources, stac_client, data_dir)}
        for c in wanted:
            if c["quantity"] not in DEM_QUANTITIES:
                continue
            r = rows.get(c["id"], {"error": "not computed"})
            if "error" in r:
                out.append({"criterion": c["id"], "error": r["error"]})
                continue
            v = round(r["value"], 3)
            items = f"; DTMs {', '.join(r['items'])}" if r.get("items") else ""
            cite = (
                f"{r['quantity']} over the {profile['reference_site']['radius_km']} km footprint "
                f"at {r['baseline_m']:g} m baseline, planetary/dem.py (T072); coverage "
                f"{r['coverage']:.2f}{items}"
            )
            out.append(
                {
                    "criterion": c["id"],
                    "measured": {
                        "value": v,
                        "unit": r["unit"],
                        "baseline_m": r["baseline_m"],
                        "coverage": r["coverage"],
                    },
                    "current_target": c.get("target"),
                    "proposed": {
                        "target": {"min": v, "max": v},
                        "value_status": "measured",
                        "sources.target": [
                            _source_entry(_entry(sources, r["source_id"]), today, cite)
                        ],
                    },
                }
            )
    minerals = [c for c in wanted if c["quantity"] in MINERAL_QUANTITIES]
    if minerals:
        res, obs = _crism_fractions(profile, sources, mineral_classes, data_dir, max_crism_obs, ode)
        xw = Crosswalk(mineral_classes)
        for c in minerals:
            if res is None or res["state"] != "KNOWN":
                out.append(
                    {"criterion": c["id"], "error": "no CRISM MTRDR data over the footprint"}
                )
                continue
            fr = res["mineral_class_fractions"]
            present = sorted(
                (k for k, v in fr.items() if v is not None and v >= min_class_fraction),
                key=lambda k: (-fr[k], k),
            )
            thresholds = ", ".join(
                f"{k} {t['parameter']}>={t['threshold']} ({t['status']})"
                for k, t in res["thresholds"].items()
            )
            cite = (
                f"CRISM MTRDR summary parameters, observations {', '.join(obs)}; class "
                f"fraction >= {min_class_fraction:g} of valid pixels; thresholds: {thresholds}"
            )
            if c["quantity"] == "mineral_class_fractions":
                target = {"classes": present}
            else:
                target = {"value": any(xw.is_aqueous(k) for k in present)}
            out.append(
                {
                    "criterion": c["id"],
                    "measured": {"fractions": fr, "valid_pixels": res["valid_pixels"]},
                    "current_target": c.get("target"),
                    "proposed": {
                        "target": target,
                        "value_status": "measured",
                        "sources.target": [
                            _source_entry(_entry(sources, "crism-mtrdr-ode"), today, cite)
                        ],
                    },
                }
            )
    return out


def load_profile(path) -> dict:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))
