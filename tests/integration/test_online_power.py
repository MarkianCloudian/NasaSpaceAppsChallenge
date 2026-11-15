"""T022 online check (skipped by default; run `pytest -m online`)."""

from __future__ import annotations

import pytest

from analogfinder.sources.power import PowerSource

pytestmark = pytest.mark.online

ENTRY = {
    "source_id": "nasa-power",
    "dataset_version": "climatology-regional",
    "rate_limit": {"requests": 1, "per_seconds": 2},
    "endpoint": "https://power.larc.nasa.gov/api/",
}


def test_one_tile_then_cache_hit_makes_no_requests(tmp_path):
    src = PowerSource(ENTRY, tmp_path)
    calls = []
    orig = src.session.get

    def counting(*a, **k):
        calls.append(a)
        return orig(*a, **k)

    src.session.get = counting
    req = {"bbox": [0, 0, 2, 2], "parameters": ["T2M"]}
    res = src.fetch(req)
    assert len(calls) == 1 and (res.path / "T2M.json").exists()
    src.fetch(req)
    assert len(calls) == 1
