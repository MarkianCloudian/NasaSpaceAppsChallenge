"""T022: POWER tiling and adapter behaviour with a fake HTTP session."""

import pytest

from analogfinder.errors import SourceError
from analogfinder.sources.base import EmptyResult, TransientError
from analogfinder.sources.power import PowerSource, tile_bbox

ENTRY = {
    "source_id": "nasa-power",
    "dataset_version": "test",
    "rate_limit": {"requests": 1000, "per_seconds": 1},
    "endpoint": "https://power.example/api/",
    "retries": 0,
}


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self.body, self.text = status, body, "err"

    def json(self):
        return self.body


class Session:
    def __init__(self, *resps):
        self.calls, self.resps = [], list(resps)

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.resps.pop(0) if self.resps else Resp(200, {"features": [{"x": 1}]})


def test_tiles_respect_limits_and_cover():
    tiles = tile_bbox((-10, -5, 25, 4))
    assert all(2 <= x1 - x0 <= 10 and 2 <= y1 - y0 <= 10 for x0, y0, x1, y1 in tiles)
    assert min(t[0] for t in tiles) == -10 and max(t[2] for t in tiles) == 25
    assert min(t[1] for t in tiles) == -5 and max(t[3] for t in tiles) == 4
    assert len(tiles) == 4 * 1


def test_small_and_edge_boxes_widened_inside_globe():
    (t,) = tile_bbox((179.5, 89.5, 180, 90))
    assert t == (178.0, 88.0, 180.0, 90.0)


def test_invalid_bbox():
    with pytest.raises(SourceError):
        tile_bbox((10, 0, 5, 1))


def test_fetch_one_request_per_parameter_then_cached(tmp_path):
    s = Session()
    src = PowerSource(ENTRY, tmp_path, session=s)
    req = {"bbox": [0, 0, 5, 5], "parameters": ["T2M", "RH2M"]}
    res = src.fetch(req)
    assert len(s.calls) == 2
    assert s.calls[0][0] == "https://power.example/api/temporal/climatology/regional"
    assert s.calls[0][1]["community"] == "RE" and s.calls[0][1]["format"] == "JSON"
    assert (res.path / "T2M.json").exists() and (res.path / "RH2M.json").exists()
    src.fetch(req)
    assert len(s.calls) == 2


def test_errors(tmp_path):
    req = {"bbox": [0, 0, 5, 5], "parameters": ["T2M"]}
    with pytest.raises(TransientError):
        PowerSource(ENTRY, tmp_path / "a", session=Session(Resp(503))).fetch(req)
    with pytest.raises(SourceError):
        PowerSource(ENTRY, tmp_path / "b", session=Session(Resp(422))).fetch(req)
    with pytest.raises(EmptyResult):
        PowerSource(ENTRY, tmp_path / "c", session=Session(Resp(200, {"features": []}))).fetch(req)
    with pytest.raises(SourceError):
        PowerSource(ENTRY, tmp_path / "d", session=Session()).fetch(
            {"bbox": [0, 0, 20, 5], "parameters": ["T2M"]}
        )
