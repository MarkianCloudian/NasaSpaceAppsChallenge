"""Profile validation, data-model *Validation rules (B1)* (plan B1, task T068).

`validate(draft, config) -> list[str]` returns every problem (empty list = valid); each message
starts with `rule <n>:` and the JSON path of the field, e.g.
`rule 6: $.criteria[3].baseline_m: ...`.

`config` is a mapping with the loaded configuration: `purposes`, `settings`, `sources`,
`layers` (as returned by `analogfinder.config`), and optionally `profiles_dir` for rule 10.
`load_validation_config(config_dir, profiles_dir)` builds it from disk.

Rules:
 1  schema-valid (profile.schema.json)
 2  purpose exists; categories in the enum
 3  weights: frozen `weights` of scored criteria sum to 1 ± 1e-6; `direct` weights given for all
    scored criteria (and summing to 1)
 4  category override without `reason`
 5  `comparison = absolute` with a quantity in `settings.earth_impossible_quantities`
 6  scale-dependent quantity (slope*, *roughness*, relief) without `baseline_m`; grid/both
    criteria must match a `layers.json` output baseline within 1 %; refinement criteria must use
    the refinement baseline (30 m, research D-020)
 7  `class_overlap` without `class_map` or `valid_bands`
 8  unknown Earth `source_id`; grid criterion whose quantity is no `layers.json` output
 9  target/tolerance shape inconsistent with `scoring_rule`
10  frozen id@version exists with a different content hash (FR-009)
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .. import config as cfg
from .load import content_hash, frozen_path

CATEGORIES = (
    "geology",
    "terrain",
    "thermal",
    "resources",
    "atmosphere",
    "biology",
    "subsurface",
    "operations",
)
SCALE_DEPENDENT = re.compile(r"^slope|roughness|^relief$")
REFINEMENT_BASELINE_M = 30.0  # research D-020: fine terrain is computed at 30 m
BASELINE_TOL = 0.01
SUM_TOL = 1e-6


def load_validation_config(config_dir=None, profiles_dir=None) -> dict[str, Any]:
    return {
        "purposes": cfg.load_purposes(config_dir),
        "settings": cfg.load_settings(config_dir),
        "sources": cfg.load_sources(config_dir),
        "layers": cfg.load_layers(config_dir),
        "profiles_dir": profiles_dir,
    }


def _near(value: float, reference: float) -> bool:
    return abs(value - reference) <= BASELINE_TOL * reference


def _scored(criteria):
    return [(i, c) for i, c in enumerate(criteria) if c.get("comparison") != "not_comparable"]


def _layer_outputs(layers: Mapping[str, Any]) -> list[dict]:
    return [o for entry in layers.get("layers", []) for o in entry.get("outputs", [])]


def _check_shape(c: dict, p: str) -> list[str]:
    rule, tgt, tol = c.get("scoring_rule"), c.get("target") or {}, c.get("tolerance") or {}
    e = []
    if rule in ("trapezoid", "gaussian"):
        if not ({"min", "max"} & set(tgt)) or all(tgt.get(k) is None for k in ("min", "max")):
            e.append(f"rule 9: {p}.target: {rule} needs a range target with min and/or max")
        extra = set(tol) - {"low", "high"}
        if extra:
            e.append(f"rule 9: {p}.tolerance: {rule} takes low/high, not {sorted(extra)}")
        lo, hi = tgt.get("min"), tgt.get("max")
        if lo is not None and hi is not None and lo > hi:
            e.append(f"rule 9: {p}.target: min {lo} > max {hi}")
    elif rule == "percentile":
        if "percentile" not in tgt:
            e.append(f"rule 9: {p}.target: percentile rule needs target.percentile")
        if "percentile" not in tol:
            e.append(f"rule 9: {p}.tolerance: percentile rule needs tolerance.percentile")
    elif rule == "boolean":
        if not isinstance(tgt.get("value"), bool):
            e.append(f"rule 9: {p}.target: boolean rule needs target.value true/false")
    elif rule == "class_overlap":
        if not tgt.get("classes"):
            e.append(f"rule 9: {p}.target: class_overlap needs target.classes")
    return e


def validate(draft: dict, config: Mapping[str, Any]) -> list[str]:
    name = f"{draft.get('profile_id', '?')}@{draft.get('version', '?')}"
    errs = [f"rule 1: {m}" for m in cfg.validate_against(draft, "profile.schema.json", name)]
    criteria = draft.get("criteria") or []
    if not isinstance(criteria, list):
        return errs

    # 2 purpose and categories
    purposes = {p["purpose_id"]: p for p in config["purposes"]["purposes"]}
    if draft.get("purpose") not in purposes:
        errs.append(f"rule 2: $.purpose: unknown purpose {draft.get('purpose')!r}")
    for i, c in enumerate(criteria):
        if c.get("category") not in CATEGORIES:
            errs.append(
                f"rule 2: $.criteria[{i}].category: {c.get('category')!r} not in {CATEGORIES}"
            )

    # 3 weights
    scored = _scored(criteria)
    given = [(i, c) for i, c in scored if "weight" in c]
    if given and len(given) != len(scored):
        missing = [c.get("id") for _, c in scored if "weight" not in c]
        errs.append(f"rule 3: $.criteria: direct weights missing for {missing} in {name}")
    elif given:
        total = sum(float(c["weight"]) for _, c in given)
        if abs(total - 1.0) > SUM_TOL:
            errs.append(
                f"rule 3: $.criteria[*].weight: weights of {name} sum to {total:.6f}, expected 1"
            )
    if "weights" in draft:
        w = draft["weights"]
        ids = {c.get("id") for _, c in scored}
        total = sum(float(v) for k, v in w.items() if k in ids)
        if abs(total - 1.0) > SUM_TOL:
            errs.append(
                f"rule 3: $.weights: frozen weights of {name} sum to {total:.6f}, expected 1"
            )
        if ids - set(w):
            errs.append(f"rule 3: $.weights: no weight for scored criteria {sorted(ids - set(w))}")

    # 4 category overrides need a reason
    for cat, ov in (draft.get("category_overrides") or {}).items():
        if not isinstance(ov, dict) or not str(ov.get("reason", "")).strip():
            errs.append(
                f"rule 4: $.category_overrides.{cat}: override of category {cat!r} needs a reason"
            )

    impossible = set(config["settings"].get("earth_impossible_quantities", []))
    source_ids = {s["source_id"] for s in config["sources"]["sources"]}
    outputs = _layer_outputs(config["layers"])
    for i, c in enumerate(criteria):
        p = f"$.criteria[{i}]"
        q, scale, comp = c.get("quantity", ""), c.get("evaluation_scale"), c.get("comparison")
        # 5
        if comp == "absolute" and q in impossible:
            errs.append(
                f"rule 5: {p}.comparison: {c.get('id')} ({q}) cannot be reproduced on Earth; "
                f"use 'normalized' or 'not_comparable'"
            )
        # 6
        if comp != "not_comparable" and SCALE_DEPENDENT.search(q):
            b = c.get("baseline_m")
            if b is None:
                errs.append(
                    f"rule 6: {p}.baseline_m: scale-dependent quantity {q!r} needs baseline_m"
                )
            elif scale in ("grid", "both"):
                matches = [
                    o["baseline_m"]
                    for o in outputs
                    if q in (o.get("quantity"), o.get("layer_id")) and o.get("baseline_m")
                ]
                if not any(_near(b, m) for m in matches):
                    errs.append(
                        f"rule 6: {p}.baseline_m: {b} m does not match a layers.json output "
                        f"baseline for {q!r} ({matches or 'none'})"
                    )
            elif scale == "refinement" and not _near(b, REFINEMENT_BASELINE_M):
                errs.append(
                    f"rule 6: {p}.baseline_m: refinement criteria use "
                    f"{REFINEMENT_BASELINE_M:g} m, got {b}"
                )
        # 7
        if c.get("scoring_rule") == "class_overlap":
            for k in ("class_map", "valid_bands"):
                if not c.get(k):
                    errs.append(f"rule 7: {p}.{k}: class_overlap needs {k}")
        # 8
        for j, sid in enumerate((c.get("sources") or {}).get("earth") or []):
            if sid not in source_ids:
                errs.append(f"rule 8: {p}.sources.earth[{j}]: unknown source_id {sid!r}")
        if comp != "not_comparable" and scale == "grid":
            if not any(q in (o.get("quantity"), o.get("layer_id")) for o in outputs):
                errs.append(
                    f"rule 8: {p}.quantity: {q!r} is not an output of any layers.json entry"
                )
        # 9
        if comp != "not_comparable":
            errs += _check_shape(c, p)

    # 10 frozen version with another hash
    pdir = config.get("profiles_dir")
    if pdir and draft.get("profile_id") and draft.get("version"):
        try:
            path = frozen_path(name, pdir)
        except Exception:  # noqa: BLE001 — malformed id/version is already a rule 1 error
            path = None
        if path is not None and path.exists():
            stored = json.loads(Path(path).read_text(encoding="utf-8")).get("content_hash")
            if stored and stored != content_hash(draft):
                errs.append(
                    f"rule 10: $.version: {name} is already frozen with different content; "
                    f"bump the version"
                )
    return errs


def summary(draft: dict) -> dict[str, Any]:
    crit = draft.get("criteria") or []
    scored = [c for c in crit if c.get("comparison") != "not_comparable"]
    return {
        "profile_id": draft.get("profile_id"),
        "version": draft.get("version"),
        "scored": len(scored),
        "veto": sum(1 for c in scored if c.get("veto") is not None),
        "normalized": sum(1 for c in scored if c.get("comparison") == "normalized"),
        "not_comparable": len(crit) - len(scored),
    }
