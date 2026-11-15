"""Small in-code criteria and profiles for unit tests (not the T034 fixture files)."""

from __future__ import annotations

from typing import Any

from analogfinder.types import Criterion, Profile


def criterion(cid: str = "c", **over: Any) -> Criterion:
    d: dict[str, Any] = {
        "id": cid,
        "category": "terrain",
        "quantity": "q",
        "statistic": "mean",
        "unit": "1",
        "evaluation_scale": "grid",
        "comparison": "absolute",
        "scoring_rule": "trapezoid",
        "target": {"min": 0.0, "max": 5.0},
        "tolerance": {"low": 2.0, "high": 4.0},
        "footprint_statistic": "mean",
        "value_status": "placeholder",
        "sources": {"target": [], "earth": []},
        "justification": "test",
    }
    d.update(over)
    return Criterion.from_json(d)


def profile(criteria: list[dict[str, Any]], weights: dict[str, float]) -> Profile:
    return Profile.from_frozen_json(
        {
            "profile_id": "test",
            "version": "1.0.0",
            "body": "Mars",
            "purpose": "rover_expedition",
            "reference_site": {"name": "x", "lat": 18.44, "lon": 77.45, "radius_km": 20},
            "search_constraints": {},
            "min_confidence": 0.6,
            "criteria": criteria,
            "weights": weights,
            "content_hash": "abc",
        }
    )
