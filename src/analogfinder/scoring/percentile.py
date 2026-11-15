"""Area-weighted percentiles of footprint values (research D-012, D-021, task T032).

`Percentile.build(values, weights)` takes land-aligned footprint values of the reference
population and their area weights (LandIndex.area_km2, ∝ cos latitude on the 0.05° grid).
Equal values are merged. Each distinct value v_i with weight w_i gets the mid-point cumulative
weight, rescaled so the lowest value has p = 0 and the highest p = 1:
    m_i = Σ_{j<i} w_j + w_i/2,   p_i = (m_i − m_0) / (m_last − m_0)
`lookup` interpolates linearly between stored points and clamps to [0, 1] outside the range.

Saved as JSON (sorted values + p) in a directory given by the pipeline, e.g.
`data/stages/screen/<screen_fp>/percentiles/<criterion_id>.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

POPULATIONS = ("eligible", "all_land", "ice_free_land")
ICE_FREE_MAX = 0.5


@dataclass(frozen=True)
class Percentile:
    values: np.ndarray  # sorted distinct values
    p: np.ndarray  # percentile of each value, 0..1
    n_cells: int

    @classmethod
    def build(cls, values: np.ndarray, weights: np.ndarray) -> Percentile:
        v = np.asarray(values, dtype="float64").ravel()
        w = np.asarray(weights, dtype="float64").ravel()
        ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
        v, w = v[ok], w[ok]
        if v.size == 0:
            return cls(np.array([]), np.array([]), 0)
        uniq, inv = np.unique(v, return_inverse=True)
        wu = np.bincount(inv, weights=w)
        mid = np.cumsum(wu) - wu / 2
        span = mid[-1] - mid[0]
        p = (mid - mid[0]) / span if span > 0 else np.full(uniq.shape, 0.5)
        return cls(uniq, p, int(v.size))

    def lookup(self, x: Any) -> np.ndarray:
        v = np.asarray(x, dtype="float64")
        if self.values.size == 0:
            return np.full(v.shape, np.nan)
        if self.values.size == 1:
            out = np.full(v.shape, 0.5)
        else:
            out = np.interp(v, self.values, self.p, left=0.0, right=1.0)
        return np.where(np.isfinite(v), out, np.nan)

    def to_json(self) -> dict:
        return {
            "n_cells": self.n_cells,
            "values": [float(x) for x in self.values],
            "p": [float(x) for x in self.p],
        }

    @classmethod
    def from_json(cls, d: dict) -> Percentile:
        return cls(
            np.asarray(d["values"], dtype="float64"),
            np.asarray(d["p"], dtype="float64"),
            int(d["n_cells"]),
        )


def population_mask(
    name: str,
    land_mask: np.ndarray,
    constraints_mask: np.ndarray | None = None,
    snow_ice_footprint: np.ndarray | None = None,
) -> np.ndarray:
    """Cells forming the reference population (research D-021); arrays are land-aligned."""
    land = np.asarray(land_mask, bool)
    if name == "all_land":
        return land
    if name == "eligible":
        if constraints_mask is None:
            raise ValueError("population 'eligible' needs the hard-constraint mask")
        return land & np.asarray(constraints_mask, bool)
    if name == "ice_free_land":
        if snow_ice_footprint is None:
            raise ValueError("population 'ice_free_land' needs the footprint snow/ice fraction")
        si = np.asarray(snow_ice_footprint, dtype="float64")
        return land & np.isfinite(si) & (si < ICE_FREE_MAX)
    raise ValueError(f"unknown percentile population {name!r}; expected one of {POPULATIONS}")


def save(pct: Percentile, directory: Path, criterion_id: str) -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{criterion_id}.json"
    path.write_text(json.dumps(pct.to_json()), encoding="utf-8")
    return path


def load(directory: Path, criterion_id: str) -> Percentile:
    path = Path(directory) / f"{criterion_id}.json"
    return Percentile.from_json(json.loads(path.read_text(encoding="utf-8")))
