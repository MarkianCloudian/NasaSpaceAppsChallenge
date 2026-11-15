"""Criterion weights from ranks (research D-003, task T025).

ROC (rank-order centroid) for n ranked items: w_k = (1/n) · Σ_{j=k..n} 1/j.
Ties: tied items share the mean of the weights of the positions they occupy (ranks are only
used to order items, so 1,1,2 and 1,1,3 give the same result).

Two levels:
  category weight W_c — ROC over the purpose's `category_ranks` (method roc) or the purpose's
      `category_weights` (method direct); profile `category_overrides` may replace a rank or fix a
      weight (each override needs a `reason`, enforced by the schema). Categories without a scored
      criterion are dropped and the rest renormalised to 1.
  within-category weight w_i|c — ROC over the scored criteria's `rank_in_category`.
Final w_i = W_c(i) × w_i|c. `not_comparable` criteria get no weight.

Method `direct`: if every scored criterion carries `weight`, those are the final weights and
only their sum is checked (must be 1 ± 1e-6).

All weights are rounded to 6 decimals; the rounding residue goes to the largest weight so the
sum is exactly 1.
"""

from __future__ import annotations

from ..errors import ValidationError

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
SUM_TOL = 1e-6


def roc(n: int) -> list[float]:
    return [sum(1.0 / j for j in range(k, n + 1)) / n for k in range(1, n + 1)]


def roc_ranked(ranks: dict) -> dict:
    """{item: rank} -> {item: ROC weight} with tie sharing. Order of equal ranks is by item id."""
    if not ranks:
        return {}
    items = sorted(ranks, key=lambda i: (ranks[i], str(i)))
    w = roc(len(items))
    out, pos = {}, 0
    while pos < len(items):
        end = pos
        while end + 1 < len(items) and ranks[items[end + 1]] == ranks[items[pos]]:
            end += 1
        share = sum(w[pos : end + 1]) / (end - pos + 1)
        for i in items[pos : end + 1]:
            out[i] = share
        pos = end + 1
    return out


def round_to_one(weights: dict, ndigits: int = 6) -> dict:
    if not weights:
        return {}
    r = {k: round(v, ndigits) for k, v in weights.items()}
    largest = max(sorted(r), key=lambda k: r[k])
    r[largest] = round(r[largest] + round(1.0 - sum(r.values()), ndigits), ndigits)
    return r


def scored(profile) -> list[dict]:
    return [c for c in profile["criteria"] if c["comparison"] != "not_comparable"]


def _category_weights(present: set, purpose: dict, overrides: dict) -> dict:
    if purpose["weight_method"] == "roc":
        ranks = dict(purpose["category_ranks"])
        for cat, ov in overrides.items():
            if "rank" in ov:
                ranks[cat] = ov["rank"]
        base = roc_ranked(ranks)
    else:
        base = dict(purpose["category_weights"])
    fixed = {c: overrides[c]["weight"] for c in present if "weight" in overrides.get(c, {})}
    free = {c: base[c] for c in present if c not in fixed}
    remainder = 1.0 - sum(fixed.values())
    if remainder < -SUM_TOL:
        raise ValidationError(f"category override weights sum to {sum(fixed.values()):.6f} > 1")
    tot = sum(free.values())
    if free and tot <= 0:
        raise ValidationError(f"categories {sorted(free)} have zero weight in the purpose")
    out = dict(fixed)
    out.update({c: v / tot * remainder for c, v in free.items()} if free else {})
    return out


def find_purpose(purposes: dict, purpose_id: str) -> dict:
    for p in purposes["purposes"]:
        if p["purpose_id"] == purpose_id:
            return p
    raise ValidationError(f"purpose {purpose_id!r} not found in purposes.json")


def compute(draft: dict, purposes: dict) -> tuple[dict[str, float], str]:
    """Return ({criterion_id: weight}, weights_method) for a draft profile.

    `purposes` is the loaded config/purposes.json; the draft's `purpose` selects the entry.
    """
    return compute_for_purpose(draft, find_purpose(purposes, draft["purpose"]))


def compute_for_purpose(profile: dict, purpose: dict) -> tuple[dict[str, float], str]:
    crit = scored(profile)
    pid = f"{profile.get('profile_id', '?')}@{profile.get('version', '?')}"
    if not crit:
        raise ValidationError(f"{pid}: no scored criteria")
    given = [c for c in crit if "weight" in c]
    if given and len(given) == len(crit):
        total = sum(c["weight"] for c in crit)
        if abs(total - 1.0) > SUM_TOL:
            raise ValidationError(f"{pid}: direct criterion weights sum to {total:.6f}, expected 1")
        return round_to_one({c["id"]: float(c["weight"]) for c in crit}), "direct"
    if given:
        raise ValidationError(
            f"{pid}: direct weights given for {len(given)} of {len(crit)} scored "
            f"criteria; give all or none"
        )
    missing = [c["id"] for c in crit if "rank_in_category" not in c]
    if missing:
        raise ValidationError(f"{pid}: rank_in_category missing for {missing}")

    by_cat = {}
    for c in crit:
        by_cat.setdefault(c["category"], []).append(c)
    W = _category_weights(set(by_cat), purpose, profile.get("category_overrides", {}))
    final = {}
    for cat, cs in by_cat.items():
        within = roc_ranked({c["id"]: c["rank_in_category"] for c in cs})
        for cid, w in within.items():
            final[cid] = W[cat] * w
    level1 = "roc" if purpose["weight_method"] == "roc" else "direct"
    return round_to_one(final), f"{level1}×roc"
