"""Grid build orchestration and manifest (plan C6, research D-001/D-011/D-019/D-021, task T044).

`build_grid(ctx)` reads `config/layers.json`, dispatches every entry to its builder class by the
`builder` name, and writes `data/grids/<grid_id>/` atomically:

* per-layer fingerprint = fingerprint of {registry entry, source dataset_version};
* `grid_id` = fingerprint of {cell definition, all layer fingerprints};
* a complete grid with that id is reused untouched;
* otherwise layers whose fingerprint exists in another grid version are copied, the rest built;
* a failing primary builder is retried with the entry's `fallback` (same outputs; the manifest
  layers name the fallback `source_id`);
* a failing layer is recorded in `missing_layers` (status `partial`), other layers are kept
  (FR-012); a partial grid is retried on the next call, reusing its good layers;
* no percentiles are computed here (they are per run, research D-021).
"""

from __future__ import annotations

import importlib
import json
import logging
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .. import config, storage
from ..errors import AnalogError, ConfigError
from ..types import GridVersion, StageContext
from . import cells

log = logging.getLogger("analogfinder.grid.build")

MANIFEST = "manifest.json"
LAND_MASK_FILE = "land_mask.tif"

# builder name -> "module:Class"; imported lazily so a builder that is not written yet only fails
# its own layers. Every name must also be allowed by schemas/layers.schema.json.
BUILDERS: dict[str, str] = {
    "modis_cmg": "analogfinder.grid.builders.modis_cmg:ModisCmgBuilder",
    "climatology_rest": "analogfinder.grid.builders.climatology_rest:ClimatologyRestBuilder",
    "landcover_fractions": "analogfinder.grid.builders.landcover_fractions:LandcoverBuilder",
    "dem_block_stats": "analogfinder.grid.builders.dem_block_stats:DemBlockStatsBuilder",
    "gridded_netcdf": "analogfinder.grid.builders.gridded_netcdf:GriddedNetcdfBuilder",
}


@dataclass(frozen=True, slots=True)
class BuildResult:
    grid: GridVersion
    reused: bool


def cell_definition(settings: Mapping) -> dict:
    """Cell definition that enters `grid_id` (research D-006; the grid is fixed by `cells`)."""
    g = settings.get("grid", {})
    size = float(g.get("cell_size_deg", cells.CELL_DEG))
    if abs(size - cells.CELL_DEG) > 1e-12:
        raise ConfigError(
            f"settings grid.cell_size_deg={size} but the grid is fixed at {cells.CELL_DEG}°"
        )
    return {
        "size_deg": cells.CELL_DEG,
        "width": cells.N_COLS,
        "height": cells.N_ROWS,
        "crs": cells.CRS,
        "origin": [cells.ORIGIN_LON, cells.ORIGIN_LAT],
        "lat_range": [float(v) for v in g.get("lat_range", [-90, 90])],
    }


def _dataset_versions(sources_config: Mapping) -> dict[str, str]:
    return {s["source_id"]: s["dataset_version"] for s in sources_config["sources"]}


def layer_fingerprint(entry: Mapping, versions: Mapping[str, str]) -> str:
    sid = entry["source_id"]
    if sid not in versions:
        raise ConfigError(f"layers.json: layer {entry['layer_id']!r} uses unknown source {sid!r}")
    key = {"entry": entry, "dataset_version": versions[sid]}
    fb = entry.get("fallback")
    if fb:
        fsid = fb["source_id"]
        if fsid not in versions:
            raise ConfigError(
                f"layers.json: fallback of {entry['layer_id']!r} uses unknown source {fsid!r}"
            )
        key["fallback_dataset_version"] = versions[fsid]
    return storage.fingerprint(key)


def fallback_entry(entry: Mapping) -> dict | None:
    """The registry entry to build when the primary builder fails (research D-008, D-019).

    The `fallback` block names only `builder`, `source_id`, `params` (and optionally
    `resampling`); the primary's `layer_id` and `outputs` are kept so exactly the same layers
    are written. Returns None when the entry has no fallback."""
    fb = entry.get("fallback")
    if not fb:
        return None
    merged = {k: v for k, v in entry.items() if k != "fallback"}
    merged.update(builder=fb["builder"], source_id=fb["source_id"], params=fb.get("params", {}))
    if "resampling" in fb:
        merged["resampling"] = fb["resampling"]
    return merged


def resolve_builder(name: str, builders: Mapping | None = None):
    """Return a builder instance; unknown name -> ConfigError."""
    table = BUILDERS if builders is None else builders
    if name not in table:
        raise ConfigError(f"layers.json: unknown builder {name!r} (known: {sorted(table)})")
    target = table[name]
    if isinstance(target, str):
        module, _, cls = target.partition(":")
        try:
            return getattr(importlib.import_module(module), cls)()
        except (ImportError, AttributeError) as e:
            raise RuntimeError(f"builder {name!r} is not available yet: {e}") from e
    return target() if isinstance(target, type) else target


def _read_manifest(path: Path) -> dict | None:
    f = Path(path) / MANIFEST
    if not storage.is_complete(path) or not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _grid_dirs(data_dir) -> list[Path]:
    root = Path(data_dir) / "grids"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and "." not in p.name)


def _reuse_candidates(data_dir) -> dict[str, tuple[Path, list[dict]]]:
    """layer fingerprint -> (grid dir, manifest layer entries with that fingerprint)."""
    found: dict[str, tuple[Path, list[dict]]] = {}
    for d in _grid_dirs(data_dir):
        manifest = _read_manifest(d)
        if not manifest:
            continue
        by_fp: dict[str, list[dict]] = {}
        for layer in manifest.get("layers", []):
            by_fp.setdefault(layer["fingerprint"], []).append(layer)
        for fp, layers in by_fp.items():
            if all((d / layer["file"]).is_file() for layer in layers):
                found.setdefault(fp, (d, layers))
    return found


def load_grid(path) -> GridVersion:
    path = Path(path)
    manifest = _read_manifest(path)
    if manifest is None:
        raise ConfigError(f"{path}: not a complete grid version")
    return GridVersion(grid_id=path.name, path=path, manifest=manifest)


def _order(entries: list[dict]) -> list[dict]:
    """Layers producing `land_mask` first: other builders read it from the stage dir."""
    return sorted(
        entries, key=lambda e: 0 if any(o["layer_id"] == "land_mask" for o in e["outputs"]) else 1
    )


def _build(entry: dict, fp: str, ctx: StageContext, builders, candidates) -> list[dict]:
    expected = [o["layer_id"] for o in entry["outputs"]]
    hit = candidates.get(fp)
    if hit and {layer["layer_id"] for layer in hit[1]} >= set(expected):
        src_dir, layers = hit
        for layer in layers:
            shutil.copy2(src_dir / layer["file"], ctx.stage_dir / layer["file"])
        log.info("%s: copied from grid %s", entry["layer_id"], src_dir.name)
        return [dict(layer) for layer in layers]
    try:
        layers = resolve_builder(entry["builder"], builders).build(entry, ctx)
    except Exception as exc:  # noqa: BLE001 - any primary failure may be rescued by the fallback
        fb = fallback_entry(entry)
        if fb is None:
            raise
        log.warning(
            "%s: primary %s/%s failed (%s); building fallback %s/%s",
            entry["layer_id"],
            entry["builder"],
            entry["source_id"],
            exc,
            fb["builder"],
            fb["source_id"],
        )
        try:
            layers = resolve_builder(fb["builder"], builders).build(fb, ctx)
        except Exception as exc2:  # noqa: BLE001
            raise RuntimeError(f"primary failed: {exc}; fallback failed: {exc2}") from exc2
    got = {layer["layer_id"] for layer in layers}
    if got != set(expected):
        raise RuntimeError(f"builder returned layers {sorted(got)}, expected {sorted(expected)}")
    return layers


def build_grid(ctx: StageContext, builders: Mapping | None = None) -> BuildResult:
    """Build or reuse the grid version for the configured layers (`ctx.stage_dir` is ignored; a
    per-build directory under `<data_dir>/grids/` is used and passed to the builders)."""
    t0 = time.monotonic()
    layers_cfg = config.load_layers(ctx.config_dir)
    versions = _dataset_versions(config.load_sources(ctx.config_dir))
    entries = _order(layers_cfg["layers"])
    # unknown builder names are a configuration error before any work starts
    for e in entries:
        if e["builder"] not in (BUILDERS if builders is None else builders):
            raise ConfigError(f"layers.json: unknown builder {e['builder']!r} in {e['layer_id']!r}")
    cell = cell_definition(ctx.settings)
    fps = {e["layer_id"]: layer_fingerprint(e, versions) for e in entries}
    grid_id = storage.fingerprint({"cell": cell, "layers": fps})
    final = storage.grid_dir(ctx.data_dir, grid_id)

    existing = _read_manifest(final)
    if existing and existing.get("status") == "complete":
        return BuildResult(GridVersion(grid_id, final, existing), reused=True)

    candidates = _reuse_candidates(ctx.data_dir)
    superseded = None
    if final.exists():  # partial earlier build with this id: retry, keeping its good layers
        superseded = final.with_name(f"{grid_id}.superseded-{int(time.time())}")
        final.rename(superseded)
        candidates = {
            fp: (superseded if d == final else d, layers) for fp, (d, layers) in candidates.items()
        }
    try:
        layer_entries: list[dict] = []
        missing: list[dict] = []
        with storage.atomic_dir(final) as work:
            sub = StageContext(
                stage="grid",
                stage_dir=work,
                data_dir=ctx.data_dir,
                config_dir=ctx.config_dir,
                settings=ctx.settings,
                profile=None,
                grid=None,
                sources=ctx.sources,
                log=ctx.log,
            )
            for e in entries:
                try:
                    built = _build(e, fps[e["layer_id"]], sub, builders, candidates)
                except Exception as exc:  # noqa: BLE001 - FR-012: record and keep going
                    if not isinstance(exc, AnalogError | RuntimeError):
                        log.exception("layer %s failed", e["layer_id"])
                    reason = str(exc) or type(exc).__name__
                    log.warning("layer %s failed: %s", e["layer_id"], reason)
                    for o in e["outputs"]:
                        missing.append({"layer_id": o["layer_id"], "reason": reason})
                    continue
                for layer in built:
                    layer["fingerprint"] = fps[e["layer_id"]]
                layer_entries.extend(built)
            kept = {layer["file"] for layer in layer_entries}
            for f in work.iterdir():  # drop files a failing builder left behind
                if f.is_file() and f.name not in kept:
                    f.unlink()
            manifest = {
                "grid_id": grid_id,
                "cell": {k: v for k, v in cell.items() if k != "lat_range"},
                "land_mask": LAND_MASK_FILE,
                "layers": layer_entries,
                "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "build_seconds": round(time.monotonic() - t0, 3),
                "status": "partial" if missing else "complete",
            }
            if missing:
                manifest["missing_layers"] = missing
            (work / MANIFEST).write_text(
                json.dumps(manifest, sort_keys=True, indent=1), encoding="utf-8"
            )
    except BaseException:
        if superseded is not None and not final.exists():
            superseded.rename(final)
        raise
    if superseded is not None:
        shutil.rmtree(superseded, ignore_errors=True)
    return BuildResult(GridVersion(grid_id, final, manifest), reused=False)


def status_report(data_dir) -> dict:
    """Grid versions, runs and stage-cache entries with completeness (`analog status`)."""
    data_dir = Path(data_dir)
    grids = []
    for d in _grid_dirs(data_dir):
        m = _read_manifest(d)
        grids.append(
            {
                "grid_id": d.name,
                "complete": storage.is_complete(d),
                "status": m.get("status") if m else None,
                "layers": len(m["layers"]) if m else 0,
                "missing_layers": [x["layer_id"] for x in (m or {}).get("missing_layers", [])],
                "built_at": m.get("built_at") if m else None,
            }
        )
    runs = []
    runs_root = data_dir / "runs"
    if runs_root.is_dir():
        for d in sorted(p for p in runs_root.iterdir() if p.is_dir() and "." not in p.name):
            runs.append({"run_id": d.name, "complete": storage.is_complete(d)})
    stages = []
    stages_root = data_dir / "stages"
    if stages_root.is_dir():
        for sd in sorted(p for p in stages_root.iterdir() if p.is_dir()):
            for d in sorted(p for p in sd.iterdir() if p.is_dir() and "." not in p.name):
                stages.append(
                    {"stage": sd.name, "fingerprint": d.name, "complete": storage.is_complete(d)}
                )
    return {"grids": grids, "runs": runs, "stages": stages}
