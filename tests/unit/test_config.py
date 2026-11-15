"""T008: all errors of a broken file are listed with file + JSON path."""

import json

import pytest

from analogfinder import config
from analogfinder.errors import ConfigError


def _sources(**over):
    s = {
        "source_id": "emit-l2b-min",
        "provider": "LP DAAC",
        "dataset": "EMIT L2B MIN",
        "dataset_version": "002",
        "body": "Earth",
        "route": "earthdata",
        "endpoint": "https://cmr.earthdata.nasa.gov",
        "collection": "EMITL2BMIN",
        "login": "earthdata",
        "request_unit": "granule",
        "format": "NetCDF4",
        "rate_limit": {"requests": 5, "per_seconds": 1},
        "licence": "public",
        "citation": "Green et al.",
        "docs_url": "https://lpdaac.usgs.gov/products/emitl2bminv002/",
    }
    s.update(over)
    return s


def test_sources_all_errors_listed(tmp_path):
    bad1 = _sources()
    del bad1["docs_url"]
    bad2 = _sources(source_id="b", route="ftp", fallback="nope")
    (tmp_path / "sources.json").write_text(json.dumps({"sources": [bad1, bad2]}))
    with pytest.raises(ConfigError) as e:
        config.load_sources(tmp_path)
    msg = str(e.value)
    assert "sources.json: $.sources[0]" in msg and "docs_url" in msg
    assert "$.sources[1].route" in msg


def test_unknown_fallback(tmp_path):
    (tmp_path / "sources.json").write_text(json.dumps({"sources": [_sources(fallback="missing")]}))
    with pytest.raises(ConfigError, match=r"fallback: unknown source_id 'missing'"):
        config.load_sources(tmp_path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="file not found"):
        config.load_settings(tmp_path)
