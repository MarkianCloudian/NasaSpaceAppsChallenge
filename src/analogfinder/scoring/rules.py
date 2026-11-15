"""Per-criterion scoring rules (research D-012, task T028).

Every rule maps an Earth value to a similarity score in [0, 1] and reports the deviation d (in
the criterion unit) and d / τ_eff. A missing / NaN Earth value is UNKNOWN (score None), never 0.

  trapezoid   s = 1 inside [min, max]; below: max(0, 1 − (min − x)/τ_low);
              above: max(0, 1 − (x − max)/τ_high); a null bound = no penalty on that side
  gaussian    s = exp(−(d/τ)²), d = distance outside [min, max]
  boolean     1 match / 0 mismatch
  class_overlap  weighted Jaccard Σ min(a,b) / Σ max(a,b) with hierarchy credit, each target
              class matched to its best-related Earth class (see class_overlap below)
  percentile  p = pct.lookup(x) (Percentile of the profile's population, research D-021);
              s = max(0, 1 − |p − p*| / τ_p), flagged relative=True

Uncertainty widens the tolerance: τ_eff = sqrt(τ² + σ_target² + σ_earth²), unknown σ omitted.
For percentile criteria σ is in the quantity's unit, not in percentile units, so it is not applied.
A bound with no tolerance on its side is a hard limit: s = 0 as soon as x is outside.

`score()` handles one value, `score_array()` whole land-aligned arrays (contracts/internal-api.md);
the `*_v` functions are the vectorised kernels both use. For class_overlap the crosswalk is
loaded from the criterion's `class_map` (path to config/mineral_classes.json).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from ..crosswalk import Crosswalk
from ..types import Criterion, CriterionScore

if TYPE_CHECKING:
    from .percentile import Percentile

KNOWN, UNKNOWN, NOT_COMPARABLE = "known", "unknown", "not_comparable"
REPO_ROOT = Path(__file__).resolve().parents[3]


def tau_eff(tau, target_sigma=None, earth_sigma=None):
    t = 0.0 if tau is None else float(tau)
    return math.sqrt(t * t + (target_sigma or 0.0) ** 2 + (earth_sigma or 0.0) ** 2)


def _distance_sides(x, lo, hi):
    x = np.asarray(x, dtype="float64")
    below = np.where(np.isfinite(x) & (lo is not None), (lo if lo is not None else 0.0) - x, 0.0)
    above = np.where(np.isfinite(x) & (hi is not None), x - (hi if hi is not None else 0.0), 0.0)
    return x, np.maximum(below, 0.0), np.maximum(above, 0.0)


def _ratio(d, tau):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(d > 0, d / tau if tau > 0 else np.inf, 0.0)


def trapezoid_v(x, lo, hi, tau_low=None, tau_high=None, target_sigma=None, earth_sigma=None):
    """Arrays (score, deviation, deviation_ratio); NaN where x is NaN."""
    x, db, da = _distance_sides(x, lo, hi)
    tl, th = (
        tau_eff(tau_low, target_sigma, earth_sigma),
        tau_eff(tau_high, target_sigma, earth_sigma),
    )
    rb, ra = _ratio(db, tl), _ratio(da, th)
    ratio = np.where(db > 0, rb, ra)
    score = np.clip(1.0 - ratio, 0.0, 1.0)
    dev = np.where(db > 0, db, da)
    nan = ~np.isfinite(x)
    return (np.where(nan, np.nan, score), np.where(nan, np.nan, dev), np.where(nan, np.nan, ratio))


def gaussian_v(x, lo, hi, tau_low=None, tau_high=None, target_sigma=None, earth_sigma=None):
    x, db, da = _distance_sides(x, lo, hi)
    tl, th = (
        tau_eff(tau_low, target_sigma, earth_sigma),
        tau_eff(tau_high, target_sigma, earth_sigma),
    )
    ratio = np.where(db > 0, _ratio(db, tl), _ratio(da, th))
    with np.errstate(over="ignore"):
        score = np.exp(-(ratio**2))
    dev = np.where(db > 0, db, da)
    nan = ~np.isfinite(x)
    return (np.where(nan, np.nan, score), np.where(nan, np.nan, dev), np.where(nan, np.nan, ratio))


def percentile_v(p, p_star, tau_p):
    p = np.asarray(p, dtype="float64")
    d = np.abs(p - p_star)
    ratio = _ratio(d, float(tau_p))
    score = np.clip(1.0 - ratio, 0.0, 1.0)
    nan = ~np.isfinite(p)
    return (np.where(nan, np.nan, score), np.where(nan, np.nan, d), np.where(nan, np.nan, ratio))


def boolean_v(x, value):
    """x: array of 0/1 (NaN unknown) or booleans. Returns (score, deviation, ratio)."""
    x = np.asarray(x, dtype="float64")
    match = (x >= 0.5) == bool(value)
    score = np.where(match, 1.0, 0.0)
    nan = ~np.isfinite(x)
    s = np.where(nan, np.nan, score)
    return s, np.where(nan, np.nan, 1.0 - s), np.where(nan, np.nan, 1.0 - s)


def class_overlap(
    earth: dict | None,
    target_classes,
    xwalk: Crosswalk,
    mode: str = "presence",
    min_fraction: float = 0.0,
) -> CriterionScore:
    """Weighted Jaccard with hierarchy credit.

    a_t (target) = 1 for each listed class. b_e (Earth) = 1 if its fraction > min_fraction
    (mode "presence", default) or the fraction itself (mode "fraction"). Presence is the default
    because Earth (EMIT band-depth detections) and Mars (thresholded CRISM parameters) area
    fractions are different measurement types (constitution II); only co-occurrence is compared.

    For each target t the best Earth item e*(t) maximises credit(t, e)·min(a_t, b_e):
      numerator   = Σ_t credit(t, e*)·min(a_t, b_e*)
      denominator = Σ_t max(a_t, b_e*) + Σ b_e over Earth items unrelated (credit 0) to every target
    Earth items related to a target but not chosen as its best match are not counted.
    deviation = number of target classes without a full match.
    """
    if not isinstance(earth, Mapping) or not earth:  # NaN / None = UNKNOWN
        return CriterionScore(None, None, None, UNKNOWN)
    b = {}
    for k, v in earth.items():
        if v is None or not math.isfinite(v):
            continue
        val = (1.0 if v > min_fraction else 0.0) if mode == "presence" else float(v)
        if val > 0:
            b[k] = val
    num = den = 0.0
    missing = 0
    for t in target_classes:
        best, best_e = 0.0, None
        for e, be in b.items():
            v = xwalk.credit(t, e) * min(1.0, be)
            if v > best or (v == best and best_e is not None and e < best_e):
                best, best_e = v, e
        num += best
        den += max(1.0, b.get(best_e, 0.0)) if best_e else 1.0
        if best < 1.0:
            missing += 1
    for e, be in b.items():
        if all(xwalk.credit(t, e) == 0 for t in target_classes):
            den += be
    s = num / den if den else 0.0
    return CriterionScore(s, float(missing), missing / len(target_classes), KNOWN)


@lru_cache(maxsize=8)
def _crosswalk(path: str) -> Crosswalk:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return Crosswalk(json.loads(p.read_text(encoding="utf-8")))


def crosswalk_for(c: Criterion) -> Crosswalk:
    if not c.class_map:
        raise ValueError(f"criterion {c.id}: class_overlap needs class_map")
    return _crosswalk(c.class_map)


def _scalar(arrs, relative: bool = False) -> CriterionScore:
    s, d, r = (float(np.asarray(a).reshape(-1)[0]) for a in arrs)
    if not math.isfinite(s):
        return CriterionScore(None, None, None, UNKNOWN, relative)
    return CriterionScore(s, d, r, KNOWN, relative)


def _is_missing(v: Any) -> bool:
    return v is None or (isinstance(v, float) and not math.isfinite(v))


def _arrays(c: Criterion, x, sigma_e: float | None, pct: Percentile | None):
    rule = c.scoring_rule
    tgt, tol = c.target or {}, c.tolerance or {}
    unc = c.uncertainty or {}
    sig_t = unc.get("target_sigma")
    sig_e = sigma_e if sigma_e is not None else unc.get("earth_sigma")
    if rule in ("trapezoid", "gaussian"):
        fn = trapezoid_v if rule == "trapezoid" else gaussian_v
        return fn(x, tgt.get("min"), tgt.get("max"), tol.get("low"), tol.get("high"), sig_t, sig_e)
    if rule == "percentile":
        if pct is None:
            raise ValueError(f"criterion {c.id}: percentile rule needs the population Percentile")
        return percentile_v(pct.lookup(x), tgt["percentile"], tol["percentile"])
    if rule == "boolean":
        return boolean_v(x, tgt["value"])
    raise ValueError(f"criterion {c.id}: rule {rule!r} has no array form")


def score(
    c: Criterion, x: Any, sigma_e: float | None = None, pct: Percentile | None = None
) -> CriterionScore:
    """Score one Earth value. For class_overlap, x is a {class: fraction} mapping."""
    relative = c.scoring_rule == "percentile"
    if c.comparison == "not_comparable":
        return CriterionScore(None, None, None, NOT_COMPARABLE)
    if c.scoring_rule == "class_overlap":
        return class_overlap(x, c.target["classes"], crosswalk_for(c))
    if _is_missing(x):
        return CriterionScore(None, None, None, UNKNOWN, relative)
    if isinstance(x, bool):
        x = float(x)
    return _scalar(_arrays(c, x, sigma_e, pct), relative)


def score_array(
    c: Criterion, x: np.ndarray, pct: Percentile | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised score for land-aligned arrays: (scores, deviations), NaN = unknown."""
    if c.comparison == "not_comparable":
        nan = np.full(np.shape(x), np.nan)
        return nan, nan.copy()
    s, d, _ = _arrays(c, np.asarray(x, dtype="float64"), None, pct)
    return s, d
