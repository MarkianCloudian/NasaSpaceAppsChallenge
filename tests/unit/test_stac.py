"""T020 unit tests for the STAC adapter (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from analogfinder.sources import stac as stac_mod
from analogfinder.sources.base import EmptyResult
from analogfinder.sources.stac import StacSource, _is_planetary_computer

ENTRY = {
    "source_id": "t-stac",
    "dataset_version": "1",
    "route": "stac",
    "endpoint": "https://example.org/stac/v1",
    "collection": "demo",
    "login": "none",
    "rate_limit": {"requests": 100, "per_seconds": 1},
    "retries": 0,
}


def _item(item_id, assets):
    return SimpleNamespace(
        id=item_id, assets={k: SimpleNamespace(href=v) for k, v in assets.items()}
    )


def test_planetary_computer_detection():
    assert _is_planetary_computer("https://planetarycomputer.microsoft.com/api/stac/v1")
    assert not _is_planetary_computer("https://example.org/planetarycomputer.microsoft.com")


def test_fetch_records_urls(tmp_path, monkeypatch):
    src = StacSource(ENTRY, tmp_path)
    monkeypatch.setattr(
        src,
        "search",
        lambda req: [_item("a", {"elevation": "https://x/a.tif", "o": "https://x/o"})],
    )
    res = src.fetch({"bbox": [0, 0, 1, 1], "assets": ["elevation"]})
    rec = json.loads((res.path / "request.json").read_text())
    assert rec["resolved"] == [{"id": "a", "assets": {"elevation": "https://x/a.tif"}}]
    assert res.source_id == "t-stac"


def test_empty_search_raises(tmp_path, monkeypatch):
    src = StacSource(ENTRY, tmp_path)
    monkeypatch.setattr(src, "search", lambda req: [])
    with pytest.raises(EmptyResult):
        src.fetch({"bbox": [0, 0, 1, 1]})


def test_probe_uses_collection_url(tmp_path, monkeypatch):
    seen = []

    def fake_get(url, timeout):
        seen.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(stac_mod.requests, "get", fake_get)
    res = StacSource(ENTRY, tmp_path).probe()
    assert seen == ["https://example.org/stac/v1/collections/demo"]
    assert res.reachable and res.login_present
