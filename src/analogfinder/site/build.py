"""Static results site: `analog site` and `analog publish` (plan F1–F5, contracts/site.md,
research D-018, D-022, D-023, D-025; tasks T060, T064).

`collect_inputs` takes a snapshot `site_inputs.json` of everything the pages show besides the
results: the frozen profile (content hash checked against the run record), the used
`config/sources.json` entries, the grid-manifest layer entries and the calibration summary.
`render` builds the pages **only** from that snapshot and `results.json`, never from live
configuration, so a site rebuilt for an old run is unchanged by later config edits.

`build_site` renders into the site stage directory `data/stages/site/<site_fp>/` (atomic,
reused when complete). `publish` refuses screening previews and runs that are not validated
against known analogs (no or flagged `calibration.json`) with exit code 8, unless
`--allow-unvalidated` is given (then every page carries the "Not validated" banner), and
replaces `public/` as a whole through `public.tmp-<random>`.

Deviation from the T060 text: the site stage is not linked into `data/runs/<run_id>/site/` and
no new run record is written for it (`analog site` is a standalone stage here, T066 not done);
the stage directory is printed instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import secrets
import shutil
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .. import config, errors, stage_io, storage

log = logging.getLogger("analogfinder.site.build")

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"
BASEMAP = HERE / "basemap" / "land_110m.svgpath"
SITE_INPUTS = "site_inputs.json"
SCALE = 10  # equirectangular viewBox 3600 x 1800, same as basemap/make_basemap.py
VIEW_W, VIEW_H = 360 * SCALE, 180 * SCALE
CALIBRATION = "calibration.json"
UNVALIDATED_TITLE = "Not validated against known analogs"

CLOUDFLARE_README = """This directory is the published Earth Analog Finder site (static files only).

GitHub Pages: .github/workflows/pages.yml uploads this directory on push to main.
Cloudflare Pages: no build command; build output directory: public
"""


# --- run lookup ---------------------------------------------------------------------------


def latest_run_id(data_dir) -> str:
    """Newest complete run in `data/runs/index.json`."""
    path = Path(data_dir) / "runs" / "index.json"
    index = stage_io.read_json(path) if path.exists() else {}
    runs = sorted(
        (r["date"], r["run_id"])
        for rs in index.values()
        for r in rs
        if storage.is_complete(storage.run_dir(data_dir, r["run_id"]))
    )
    if not runs:
        raise errors.ValidationError("no complete runs yet: run `analog run --profile ID@VER`")
    return runs[-1][1]


def load_results(data_dir, run_id: str) -> dict:
    path = storage.run_dir(data_dir, run_id) / "results.json"
    if not path.exists():
        raise errors.ValidationError(f"run {run_id}: no results.json (partial run?)")
    return stage_io.read_json(path)


# --- snapshot (research D-023) -----------------------------------------------------------


def calibration_of(data_dir, run_id: str) -> dict | None:
    path = storage.run_dir(data_dir, run_id) / CALIBRATION
    return stage_io.read_json(path) if path.exists() else None


def validation_reasons(calibration: dict | None) -> list[str]:
    """Why a run is not validated against known analogs; empty when it is (D-018)."""
    if calibration is None:
        return ["calibration_not_run"]
    if calibration.get("flag_for_review"):
        return list(calibration.get("flag_reasons") or ["flag_for_review"])
    return []


def collect_inputs(results: dict, data_dir, config_dir, profiles_dir) -> dict:
    rr = results["run_record"]
    p = rr["profile"]
    frozen_path = Path(profiles_dir) / "frozen" / f"{p['id']}@{p['version']}.json"
    if not frozen_path.exists():
        raise errors.ValidationError(f"frozen profile {frozen_path} not found")
    profile = json.loads(frozen_path.read_text(encoding="utf-8"))
    if profile.get("content_hash") != p.get("content_hash"):
        raise errors.ProfileConflictError(
            f"{frozen_path.name}: content_hash differs from the run record of {rr['run_id']}"
        )
    manifest_path = storage.grid_dir(data_dir, rr["grid_id"]) / "manifest.json"
    manifest = stage_io.read_json(manifest_path) if manifest_path.exists() else None
    used = {s["source_id"] for s in rr.get("sources", [])}
    used |= {sid for c in profile["criteria"] for sid in c.get("sources", {}).get("earth", [])}
    if manifest:
        used |= {layer["source_id"] for layer in manifest.get("layers", [])}
    entries = {e["source_id"]: e for e in config.load_sources(config_dir)["sources"]}
    keys = (
        "source_id",
        "provider",
        "dataset",
        "dataset_version",
        "licence",
        "citation",
        "docs_url",
    )
    sources = [{k: entries[s].get(k) for k in keys} for s in sorted(used) if s in entries]
    accessed = {s["source_id"]: s.get("accessed") for s in rr.get("sources", [])}
    for s in sources:
        s["accessed"] = accessed.get(s["source_id"])
    grid = None
    if manifest:
        lkeys = ("layer_id", "source_id", "dataset_version", "reference_period", "resampling")
        grid = {
            "grid_id": manifest.get("grid_id", rr["grid_id"]),
            "status": manifest.get("status"),
            "built_at": manifest.get("built_at"),
            "missing_layers": manifest.get("missing_layers", []),
            "layers": [
                {**{k: layer.get(k) for k in lkeys}, "baseline_m": layer.get("baseline_m")}
                for layer in manifest.get("layers", [])
            ],
        }
    return {
        "profile": profile,
        "sources": sources,
        "grid": grid,
        "calibration": calibration_of(data_dir, rr["run_id"]),
    }


# --- formatting --------------------------------------------------------------------------


def project(lat: float, lon: float) -> tuple[float, float]:
    return round((lon + 180.0) * SCALE, 1), round((90.0 - lat) * SCALE, 1)


def num(x: Any, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    mag = math.floor(math.log10(abs(x)))
    dec = max(0, digits - 1 - mag)
    return f"{x:.{dec}f}".rstrip("0").rstrip(".") if dec else f"{x:.0f}"


def pct(x: Any) -> str:
    return "—" if x is None else f"{100.0 * x:.1f}%"


def coords(lat: float, lon: float) -> str:
    return f"{abs(lat):.2f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.2f}°{'E' if lon >= 0 else 'W'}"


def fmt_value(v: Any, unit: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, dict):
        items = [f"{k} {num(x, 2)}" for k, x in sorted(v.items()) if x]
        return ", ".join(items) if items else "none detected"
    if isinstance(v, bool):
        return "yes" if v else "no"
    s = num(v)
    return f"{s} {unit}".strip() if unit and unit not in ("boolean", "index") else s


def fmt_target(t: dict | None, unit: str = "") -> str:
    if not t:
        return "—"
    u = f" {unit}" if unit and unit not in ("boolean", "index", "fraction") else ""
    if "percentile" in t:
        p = t["percentile"]
        side = " (lowest on Earth)" if p == 0 else " (highest on Earth)" if p == 1 else ""
        return f"Earth percentile {num(p, 2)}{side}"
    if "classes" in t:
        return ", ".join(t["classes"])
    if "value" in t:
        return fmt_value(t["value"], unit)
    lo, hi = t.get("min"), t.get("max")
    if lo is not None and hi is not None:
        return f"= {num(lo)}{u}" if lo == hi else f"{num(lo)}–{num(hi)}{u}"
    if hi is not None:
        return f"≤ {num(hi)}{u}"
    if lo is not None:
        return f"≥ {num(lo)}{u}"
    return "—"


def fmt_tolerance(t: dict | None) -> str:
    if not t:
        return "—"
    return ", ".join(f"{k} {num(v)}" for k, v in t.items())


def mode_of(criterion: dict, result: dict | None = None) -> str:
    if criterion.get("comparison") == "not_comparable":
        return "not comparable"
    if criterion.get("comparison") == "normalized" or (result or {}).get("relative"):
        return "relative"
    return "absolute"


def fmt_deviation(r: dict, criterion: dict) -> str:
    d = r.get("deviation")
    if d is None:
        return "—"
    if mode_of(criterion, r) == "relative":
        return f"{num(d, 2)} (percentile)"
    if criterion.get("scoring_rule") == "class_overlap":
        return f"{num(d)} class(es) not matched"
    return fmt_value(d, r.get("unit") or criterion.get("unit", ""))


# --- page model --------------------------------------------------------------------------


def _criteria(profile: dict) -> dict[str, dict]:
    return {c["id"]: c for c in profile["criteria"]}


def refinement_status(rr: dict) -> str:
    ref = rr.get("refinement") or {}
    stop = ref.get("stop")
    n = rr.get("settings", {}).get("site_top_n", 30)
    if stop == "bound_reached":
        return f"top {n} proven complete"
    if stop == "cap_reached":
        k = ref.get("proven_top", 0)
        return f"top results not proven complete: refinement cap reached ({k} of {n} proven)"
    if stop == "skipped":
        return "screening preview: refinement skipped"
    return "refinement status unknown"


def page_model(results: dict, inputs: dict, unvalidated: list[str], top_n: int) -> dict:
    rr = results["run_record"]
    profile = inputs["profile"]
    crit = _criteria(profile)
    preview = (rr.get("refinement") or {}).get("stop") == "skipped"
    cands = results["candidates"]
    if preview:
        shown = sorted(
            (c for c in cands if c["status"] == "screened_only"),
            key=lambda c: (-(c.get("upper_bound") or 0.0), c["area_id"]),
        )[:top_n]
    else:
        shown = sorted((c for c in cands if c["status"] == "ranked"), key=lambda c: c["rank"])
        shown = shown[:top_n]
    rows = []
    for c in shown:
        rep = c["representative"]
        x, y = project(rep["lat"], rep["lon"])
        lim = c.get("limiting_criterion")
        rows.append(
            {
                "c": c,
                "x": x,
                "y": y,
                "coords": coords(rep["lat"], rep["lon"]),
                "score": pct(c.get("overall_score")),
                "bound": pct(c.get("upper_bound")),
                "confidence": pct(c.get("confidence")),
                "limiting": lim or "—",
                "label": (c.get("label") or "").replace("_", " ") or "—",
                "href": f"c/{c['area_id']}.html",
                "criteria": [
                    {
                        "id": r["criterion_id"],
                        "category": crit.get(r["criterion_id"], {}).get("category", ""),
                        "state": r.get("state"),
                        "earth": fmt_value(r.get("earth_value"), r.get("unit", "")),
                        "target": fmt_target(r.get("target"), r.get("unit", "")),
                        "deviation": fmt_deviation(r, crit.get(r["criterion_id"], {})),
                        "ratio": num(r.get("deviation_ratio"), 2),
                        "score": num(r.get("score"), 2),
                        "weight": num(r.get("weight_effective"), 2),
                        "mode": mode_of(crit.get(r["criterion_id"], {}), r),
                        "source": r.get("source_id")
                        or ", ".join(
                            crit.get(r["criterion_id"], {}).get("sources", {}).get("earth", [])
                        )
                        or "—",
                        "note": r.get("note", ""),
                        "scale": r.get("scale_used") or "",
                    }
                    for r in c.get("results", [])
                ],
            }
        )
    weights = profile.get("weights", {})
    criteria_table = [
        {
            "id": c["id"],
            "category": c.get("category", ""),
            "quantity": c.get("quantity", ""),
            "mode": mode_of(c),
            "scale": c.get("evaluation_scale", ""),
            "target": fmt_target(c.get("target"), c.get("unit", "")),
            "tolerance": fmt_tolerance(c.get("tolerance")),
            "veto": num(c.get("veto"), 2) if c.get("veto") is not None else "—",
            "weight": num(weights.get(c["id"]), 3) if c["id"] in weights else "—",
            "status": c.get("value_status", ""),
            "sources": c.get("sources", {}).get("target", []),
        }
        for c in profile["criteria"]
    ]
    counts = rr.get("counts", {})
    return {
        "rr": rr,
        "profile": profile,
        "rows": rows,
        "preview": preview,
        "placeholder": bool(rr.get("placeholder_values")),
        "dedup_applied": bool(rr.get("dedup_applied")),
        "unvalidated": unvalidated,
        "unvalidated_title": UNVALIDATED_TITLE,
        "refinement": refinement_status(rr),
        "criteria_table": criteria_table,
        "counts": counts,
        "n_ranked": sum(1 for c in cands if c["status"] == "ranked"),
        "sources": inputs.get("sources", []),
        "grid": inputs.get("grid"),
        "calibration": inputs.get("calibration"),
        "view_w": VIEW_W,
        "view_h": VIEW_H,
    }


# --- rendering ---------------------------------------------------------------------------


def _env():
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=jinja2.select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["num"] = num
    env.filters["pct"] = pct
    return env


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def render(
    results: dict,
    inputs: dict,
    out_dir: Path,
    *,
    unvalidated: list[str] | None = None,
    top_n: int = 30,
) -> list[Path]:
    """Write the site (contracts/site.md layout) into `out_dir`; returns the written files."""
    out = Path(out_dir)
    env = _env()
    m = page_model(results, inputs, list(unvalidated or []), top_n)
    pid = m["profile"]["profile_id"]
    land = BASEMAP.read_text(encoding="ascii").strip()
    written = []

    def page(template: str, rel: str, **extra) -> None:
        depth = rel.count("/")
        root = "../" * depth
        html = env.get_template(template).render(**m, root=root, land=land, pid=pid, **extra)
        _write(out / rel, html)
        written.append(out / rel)

    page("index.html.j2", "index.html", base=f"p/{pid}/")
    page("index.html.j2", f"p/{pid}/index.html", base="")
    for row in m["rows"]:
        page("candidate.html.j2", f"p/{pid}/c/{row['c']['area_id']}.html", row=row)
    page("method.html.j2", "method.html")
    page("about.html.j2", "about.html")
    (out / "assets").mkdir(parents=True, exist_ok=True)
    for name in ("style.css", "map.js"):
        shutil.copy2(STATIC / name, out / "assets" / name)
        written.append(out / "assets" / name)
    stage_io.write_json(out / SITE_INPUTS, inputs)
    return written


def _code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(
        list(TEMPLATES.glob("*.j2")) + list(STATIC.glob("*")) + [BASEMAP, Path(__file__)]
    ):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _package_version() -> str:
    try:
        return version("analogfinder")
    except PackageNotFoundError:
        return "0"


def site_fp(results: dict, inputs: dict, unvalidated: list[str], top_n: int) -> str:
    return storage.fingerprint(
        {
            "run_id": results["run_record"]["run_id"],
            "inputs": storage.fingerprint(inputs),
            "unvalidated": unvalidated,
            "top_n": top_n,
            "package": _package_version(),
            "code": _code_hash(),
        }
    )


def snapshot(results: dict, data_dir, config_dir, profiles_dir) -> dict:
    """The run's `site_inputs.json`: taken once per run and reused for every later rebuild, so
    later edits of config files never change the site of an old run (research D-023)."""
    path = storage.stage_dir(data_dir, "site-inputs", results["run_record"]["run_id"]) / SITE_INPUTS
    if path.exists():
        return stage_io.read_json(path)
    inputs = collect_inputs(results, data_dir, config_dir, profiles_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{SITE_INPUTS}.partial-{secrets.token_hex(4)}")
    stage_io.write_json(tmp, inputs)
    os.replace(tmp, path)
    return stage_io.read_json(path)


def build_site(
    data_dir, config_dir, profiles_dir, run_id: str, settings: dict | None = None
) -> tuple[Path, bool]:
    """Render (or reuse) the site of `run_id` in `data/stages/site/<fp>/`."""
    settings = settings or config.load_settings(config_dir)
    top_n = int(settings.get("site_top_n", 30))
    results = load_results(data_dir, run_id)
    inputs = snapshot(results, data_dir, config_dir, profiles_dir)
    reasons = validation_reasons(inputs["calibration"])
    fp = site_fp(results, inputs, reasons, top_n)
    d = storage.stage_dir(data_dir, "site", fp)
    if storage.is_complete(d):
        return d, True
    with storage.atomic_dir(
        d, manifest={"stage": "site", "fingerprint": fp, "run_id": run_id}
    ) as t:
        render(results, inputs, t, unvalidated=reasons, top_n=top_n)
    return d, False


# --- publish (T064) ----------------------------------------------------------------------


def _copy_site(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns("_COMPLETE", "manifest.json", "request.json")
    shutil.copytree(src, dst, ignore=ignore)


def replace_dir(src: Path, public: Path) -> None:
    """Replace `public` as a whole: build `public.tmp-<random>`, then swap."""
    public = Path(public)
    tmp = public.with_name(f"{public.name}.tmp-{secrets.token_hex(4)}")
    _copy_site(src, tmp)
    (tmp / ".nojekyll").write_text("", encoding="utf-8")
    (tmp / "README.txt").write_text(CLOUDFLARE_README, encoding="utf-8")
    old = None
    if public.exists():
        old = public.with_name(f"{public.name}.old-{secrets.token_hex(4)}")
        os.replace(public, old)
    os.replace(tmp, public)
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def publish(
    data_dir,
    config_dir,
    profiles_dir,
    run_id: str,
    public_dir,
    allow_unvalidated: bool = False,
    out=None,
) -> int:
    """Copy the run's site into `public_dir`, or refuse with exit 8 (D-018, D-025)."""
    import sys

    out = out or sys.stderr
    results = load_results(data_dir, run_id)
    if (results["run_record"].get("refinement") or {}).get("stop") == "skipped":
        print(f"publish refused: run {run_id} is a screening preview (not ranked)", file=out)
        return errors.PUBLISH_REFUSED
    reasons = validation_reasons(calibration_of(data_dir, run_id))
    if reasons and not allow_unvalidated:
        print(
            f"publish refused: run {run_id} is not validated against known analogs "
            f"({', '.join(reasons)}); use --allow-unvalidated to publish with a banner",
            file=out,
        )
        return errors.PUBLISH_REFUSED
    site, _ = build_site(data_dir, config_dir, profiles_dir, run_id)
    replace_dir(site, Path(public_dir))
    print(f"published run {run_id} to {public_dir}", file=out)
    return errors.OK
