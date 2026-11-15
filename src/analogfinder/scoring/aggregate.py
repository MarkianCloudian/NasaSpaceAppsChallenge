"""Veto, overall score, confidence and limiting criterion (research D-012, task T030).

1. Veto first: the first KNOWN criterion (in profile order = evaluation order) whose score is
   below its veto rejects the candidate; `rejected_by` = its id, no overall score.
2. Overall S = Π s_i^(w_i / Σ_known w) over KNOWN scored criteria (`not_comparable` and
   UNKNOWN excluded, weights renormalised); any KNOWN score of 0 gives S = 0.
3. Confidence C = Σ_known w_i (frozen weights sum to 1, so C ∈ [0, 1]).
4. Limiting criterion = lowest s_i; ties -> higher weight first, then id.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from ..types import Aggregate, CriterionScore, Profile


def aggregate(scores: Mapping[str, CriterionScore], profile: Profile) -> Aggregate:
    known = []  # (id, score, weight, veto) in evaluation order
    for c in profile.criteria:
        cs = scores.get(c.id)
        if (
            c.comparison == "not_comparable"
            or cs is None
            or cs.state != "known"
            or cs.score is None
        ):
            continue
        known.append((c.id, cs.score, float(profile.weights.get(c.id, 0.0)), c.veto))
    conf = sum(w for _, _, w, _ in known)
    for cid, s, _, veto in known:
        if veto is not None and s < veto:
            return Aggregate(None, conf, cid, cid)
    if not known or conf <= 0:
        return Aggregate(None, conf, None, None)
    if any(s <= 0 and w > 0 for _, s, w, _ in known):
        overall = 0.0
    else:
        overall = math.exp(sum(w / conf * math.log(s) for _, s, w, _ in known if w > 0))
    limiting = min(known, key=lambda k: (k[1], -k[2], k[0]))[0]
    return Aggregate(overall, conf, limiting, None)


def aggregate_arrays(
    scores: Mapping[str, np.ndarray], profile: Profile
) -> tuple[np.ndarray, np.ndarray]:
    """Land-aligned version: scores {criterion_id: array} with NaN = unknown.

    Returns (overall, confidence); overall is NaN where a veto rejects the cell or nothing is
    known. Use `rejected_by_arrays` for the veto reason.
    """
    overall, conf, _ = _stack(scores, profile)
    return overall, conf


def rejected_by_arrays(scores: Mapping[str, np.ndarray], profile: Profile) -> np.ndarray:
    """Index into profile.criteria of the first vetoing criterion, −1 where none."""
    return _stack(scores, profile)[2]


def _stack(scores, profile):
    crit = [c for c in profile.criteria if c.comparison != "not_comparable" and c.id in scores]
    if not crit:
        raise ValueError("no scored criteria in the score arrays")
    s = np.stack([np.asarray(scores[c.id], dtype="float64") for c in crit])
    known = np.isfinite(s)
    w = np.array([float(profile.weights.get(c.id, 0.0)) for c in crit])
    v = np.array([np.nan if c.veto is None else float(c.veto) for c in crit])
    shape = (-1,) + (1,) * (s.ndim - 1)
    wk = np.where(known, w.reshape(shape), 0.0)
    conf = wk.sum(axis=0)
    hit = known & np.isfinite(v.reshape(shape)) & (s < np.nan_to_num(v, nan=-np.inf).reshape(shape))
    first = np.where(hit.any(axis=0), hit.argmax(axis=0), -1)
    idx = {c.id: i for i, c in enumerate(profile.criteria)}
    rejected_by = np.where(
        first >= 0, np.array([idx[c.id] for c in crit])[np.maximum(first, 0)], -1
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        expo = np.where(conf > 0, wk / conf, 0.0)
        logs = np.where(known & (wk > 0), np.log(np.where(s > 0, s, 1.0)), 0.0)
        overall = np.exp((expo * logs).sum(axis=0))
    overall = np.where((known & (wk > 0) & (s <= 0)).any(axis=0), 0.0, overall)
    overall = np.where((conf > 0) & (rejected_by < 0), overall, np.nan)
    return overall, conf, rejected_by
