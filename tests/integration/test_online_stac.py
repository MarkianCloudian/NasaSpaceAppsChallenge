"""T020 online check (skipped by default; run `pytest -m online`)."""

from __future__ import annotations

import pytest

from analogfinder.sources.stac import StacSource

pytestmark = pytest.mark.online

ENTRY = {
    "source_id": "nasadem-pc",
    "dataset_version": "1",
    "route": "stac",
    "endpoint": "https://planetarycomputer.microsoft.com/api/stac/v1",
    "collection": "nasadem",
    "login": "none",
    "rate_limit": {"requests": 5, "per_seconds": 1},
}


def test_nasadem_items_for_atacama(tmp_path):
    src = StacSource(ENTRY, tmp_path)
    assert src.probe().reachable
    items = src.search({"bbox": [-69.3, -24.3, -69.0, -24.0]})
    assert len(items) >= 1
