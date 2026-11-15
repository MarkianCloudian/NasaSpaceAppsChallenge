"""Load and validate every JSON configuration file (plan A2, task T008).

All errors of a file are collected and raised together as one ConfigError listing
file name + JSON path + message, so a broken config is fixed in one pass.
"""
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"


def _json_path(err) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path)


def _read(path: Path):
    if not path.exists():
        raise ConfigError(f"{path.name}: file not found ({path})")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path.name}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}")


def validate_against(data, schema_name: str, file_label: str) -> list[str]:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    return [f"{file_label}: {_json_path(e)}: {e.message}"
            for e in sorted(v.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))]


def _load(name: str, schema: str, config_dir=None, extra_checks=None):
    path = Path(config_dir or DEFAULT_CONFIG_DIR) / name
    data = _read(path)
    errs = validate_against(data, schema, name)
    if not errs and extra_checks:
        errs += extra_checks(data, name)
    if errs:
        raise ConfigError(f"{len(errs)} error(s) in {name}:\n  " + "\n  ".join(errs))
    return data


def _check_sources(data, name):
    ids = [s["source_id"] for s in data["sources"]]
    errs = [f"{name}: duplicate source_id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for k, s in enumerate(data["sources"]):
        fb = s.get("fallback")
        if fb and fb not in ids:
            errs.append(f"{name}: $.sources[{k}].fallback: unknown source_id {fb!r}")
    return errs


def _check_purposes(data, name):
    ids = [p["purpose_id"] for p in data["purposes"]]
    return [f"{name}: duplicate purpose_id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]


def _check_known(data, name):
    ids = [s["site_id"] for s in data["sites"]]
    return [f"{name}: duplicate site_id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]


def load_settings(config_dir=None):
    return _load("settings.json", "settings.schema.json", config_dir)


def load_sources(config_dir=None):
    return _load("sources.json", "sources.schema.json", config_dir, _check_sources)


def load_purposes(config_dir=None):
    return _load("purposes.json", "purposes.schema.json", config_dir, _check_purposes)


def load_known_analogs(config_dir=None):
    return _load("known_analogs.json", "known-analogs.schema.json", config_dir, _check_known)


def load_layers(config_dir=None):
    return _load("layers.json", "layers.schema.json", config_dir)


# --- mineral classes: no JSON Schema in contracts/, structural check in code -------------

CREDIT_KEYS = ("same_species", "same_subgroup", "same_group", "otherwise")


def check_mineral_classes(data, name="mineral_classes.json") -> list[str]:
    errs = []
    if not isinstance(data, dict):
        return [f"{name}: $: must be an object"]
    pc = data.get("partial_credit")
    if not isinstance(pc, dict) or any(not isinstance(pc.get(k), (int, float)) for k in CREDIT_KEYS):
        errs.append(f"{name}: $.partial_credit: needs numeric {', '.join(CREDIT_KEYS)}")
    groups = data.get("groups")
    species_seen, subgroups_seen = {}, set()
    if not isinstance(groups, dict) or not groups:
        errs.append(f"{name}: $.groups: must be a non-empty object")
        groups = {}
    for g, gv in groups.items():
        subs = gv.get("subgroups") if isinstance(gv, dict) else None
        if not isinstance(subs, dict) or not subs:
            errs.append(f"{name}: $.groups.{g}.subgroups: must be a non-empty object")
            continue
        for sg, species in subs.items():
            if sg in subgroups_seen:
                errs.append(f"{name}: $.groups.{g}.subgroups.{sg}: subgroup id used twice")
            subgroups_seen.add(sg)
            if not isinstance(species, list) or not species:
                errs.append(f"{name}: $.groups.{g}.subgroups.{sg}: must be a non-empty list of species")
                continue
            for sp in species:
                if sp in species_seen:
                    errs.append(f"{name}: species {sp!r} is in both {species_seen[sp]} and {sg}")
                species_seen[sp] = sg
    for k, r in enumerate(data.get("crism_rules", [])):
        p = f"{name}: $.crism_rules[{k}]"
        if r.get("class") not in subgroups_seen:
            errs.append(f"{p}.class: unknown subgroup {r.get('class')!r}")
        if not isinstance(r.get("parameter"), str):
            errs.append(f"{p}.parameter: missing")
        if not isinstance(r.get("threshold"), (int, float)):
            errs.append(f"{p}.threshold: must be a number")
        if r.get("parameter") in {e.get("parameter") for e in data.get("excluded_parameters", [])}:
            errs.append(f"{p}.parameter: {r.get('parameter')} is listed in excluded_parameters")
    for k, r in enumerate(data.get("emit_names", [])):
        p = f"{name}: $.emit_names[{k}]"
        try:
            re.compile(r.get("pattern", ""))
        except re.error as e:
            errs.append(f"{p}.pattern: invalid regex: {e}")
        sp = r.get("species")
        if sp is not None and sp not in species_seen:
            errs.append(f"{p}.species: unknown species {sp!r}")
    for k, r in enumerate(data.get("excluded_parameters", [])):
        if not r.get("parameter") or not r.get("reason"):
            errs.append(f"{name}: $.excluded_parameters[{k}]: needs parameter and reason")
    return errs


def load_mineral_classes(config_dir=None):
    path = Path(config_dir or DEFAULT_CONFIG_DIR) / "mineral_classes.json"
    data = _read(path)
    errs = check_mineral_classes(data, path.name)
    if errs:
        raise ConfigError(f"{len(errs)} error(s) in {path.name}:\n  " + "\n  ".join(errs))
    return data
