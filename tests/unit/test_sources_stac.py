"""`route: stac` adapter (T020): fake STAC client + local GeoTIFF; online check of NASADEM."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from analogfinder.sources.base import EmptyResult
from analogfinder.sources.stac import StacSource, pick_asset, request_bbox

PX = 1 / 3600


def _dem(path, west=-70.0, north=-24.0, n=720):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=n,
        height=n,
        count=1,
        dtype="int16",
        crs="EPSG:4326",
        transform=from_origin(west, north, PX, PX),
        nodata=-32768,
    ) as ds:
        ds.write(np.arange(n * n, dtype="int32").reshape(n, n).astype("int16"), 1)
    return path


def _item(iid, href):
    asset = SimpleNamespace(href=href, roles=["data"], media_type="image/tiff; profile=cog")
    preview = SimpleNamespace(href="x.png", roles=["overview"], media_type="image/png")
    return SimpleNamespace(id=iid, assets={"elevation": asset, "rendered_preview": preview})


class FakeClient:
    def __init__(self, items):
        self.items_ = items
        self.calls = 0

    def search(self, collections, bbox):
        self.calls += 1
        return SimpleNamespace(items=lambda: list(self.items_))


def _src(tmp_path, items):
    entry = {
        "source_id": "fx-stac",
        "dataset_version": "1",
        "route": "stac",
        "endpoint": "https://example.invalid/stac",
        "collection": "fx",
        "rate_limit": {"requests": 100, "per_seconds": 1},
        "retries": 0,
    }
    client = FakeClient(items)
    return StacSource(entry, tmp_path / "data", sleep=lambda s: None, client_factory=lambda: client)


def test_clips_bbox_window(tmp_path):
    tif = _dem(tmp_path / "tile.tif")
    src = _src(tmp_path, [_item("t1", str(tif))])
    bbox = [-69.95, -24.1, -69.9, -24.05]  # 0.05 deg = 180 px
    res = src.fetch({"kind": "dem", "bbox": bbox})
    (out,) = res.path.glob("*.tif")
    with rasterio.open(out) as ds:
        assert (ds.width, ds.height) == (180, 180)
        b = ds.bounds
        assert b.left == pytest.approx(-69.95) and b.top == pytest.approx(-24.05)
    meta = json.loads((res.path / "items.json").read_text())
    assert meta["items"][0]["asset"] == "elevation"


def test_no_items_or_no_overlap_is_empty(tmp_path):
    with pytest.raises(EmptyResult):
        _src(tmp_path, []).fetch({"bbox": [1, 1, 2, 2]})
    tif = _dem(tmp_path / "tile.tif")
    with pytest.raises(EmptyResult):  # item listed but raster outside the bbox
        _src(tmp_path, [_item("t1", str(tif))]).fetch({"bbox": [10, 10, 11, 11]})


def test_pick_asset_and_bbox_rules():
    it = _item("t", "a.tif")
    assert pick_asset(it)[0] == "elevation"
    with pytest.raises(Exception, match="no asset"):
        pick_asset(it, "data")
    assert request_bbox({"bounding_box": [0, 0, 1, 1]}) == (0, 0, 1, 1)
    with pytest.raises(Exception, match="invalid bbox"):
        request_bbox({"bbox": [1, 0, 0, 1]})


@pytest.mark.online
def test_online_nasadem_atacama(tmp_path):
    from analogfinder import config
    from analogfinder.sources.base import SourceRegistry

    reg = SourceRegistry.from_config(config.load_sources("config"), tmp_path)
    src = reg.get("nasadem-pc")
    assert src.probe().reachable
    bbox = [-69.95, -24.1, -69.9, -24.05]
    assert len(src.search({"bbox": bbox})) >= 1
    res = src.fetch({"kind": "dem", "bbox": bbox})
    (out,) = res.path.glob("*.tif")
    with rasterio.open(out) as ds:
        z = ds.read(1)
        assert z.size > 0 and 500 < float(np.median(z)) < 6000  # Atacama altiplano/desert
