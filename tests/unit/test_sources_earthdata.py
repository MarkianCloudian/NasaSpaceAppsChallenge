"""T021: Earthdata adapter with a faked earthaccess module (no network)."""

import pytest

from analogfinder.errors import SourceError
from analogfinder.sources import earthdata
from analogfinder.sources.base import EmptyResult

ENTRY = {
    "source_id": "modis-test",
    "route": "earthdata",
    "collection": "MOD11C3",
    "dataset_version": "061",
    "rate_limit": {"requests": 100, "per_seconds": 1},
}


class FakeAuth:
    authenticated = True


@pytest.fixture
def ea(monkeypatch):
    class Fake:
        logins = []
        granules = ["g1"]

        @classmethod
        def login(cls, strategy):
            cls.logins.append(strategy)
            raise Exception("no credentials")

        @staticmethod
        def search_datasets(**kw):
            return [{}]

        @classmethod
        def search_data(cls, **kw):
            cls.kw = kw
            return cls.granules

        @staticmethod
        def download(granules, path):
            (__import__("pathlib").Path(path) / "f.hdf").write_bytes(b"x")
            return ["f.hdf"]

    monkeypatch.setattr(earthdata, "earthaccess", Fake)
    return Fake


def test_probe_without_credentials(ea):
    r = earthdata.EarthdataSource(ENTRY, "x").probe()
    assert r.login_present is False and r.reachable is True
    assert ea.logins == ["netrc", "environment"]


def test_probe_unreachable_no_exception(ea, monkeypatch):
    def boom(**kw):
        raise OSError("down")

    monkeypatch.setattr(ea, "search_datasets", boom)
    r = earthdata.EarthdataSource(ENTRY, "x").probe()
    assert r.reachable is False and "down" in r.error


def test_login_falls_back_to_environment(ea, monkeypatch):
    def login(strategy):
        ea.logins.append(strategy)
        if strategy == "netrc":
            raise Exception("none")
        return FakeAuth()

    monkeypatch.setattr(ea, "login", login)
    assert earthdata.EarthdataSource(ENTRY, "x").probe().login_present is True
    assert ea.logins == ["netrc", "environment"]


def test_fetch_requires_login(ea, tmp_path):
    with pytest.raises(SourceError, match="login missing"):
        earthdata.EarthdataSource(ENTRY, tmp_path).fetch({"bbox": [0, 0, 1, 1]})


def test_fetch_downloads_and_caches(ea, monkeypatch, tmp_path):
    monkeypatch.setattr(ea, "login", lambda strategy: FakeAuth())
    src = earthdata.EarthdataSource(ENTRY, tmp_path)
    req = {"bbox": [0, 0, 1, 1], "temporal": ["2020-01-01", "2020-12-31"]}
    res = src.fetch(req)
    assert (res.path / "f.hdf").exists()
    assert ea.kw == {
        "short_name": "MOD11C3",
        "version": "061",
        "temporal": ("2020-01-01", "2020-12-31"),
        "bounding_box": (0, 0, 1, 1),
    }
    ea.granules = []  # second call is served from cache: no search
    assert src.fetch(req).path == res.path


def test_fetch_empty_search(ea, monkeypatch, tmp_path):
    monkeypatch.setattr(ea, "login", lambda strategy: FakeAuth())
    ea.granules = []
    with pytest.raises(EmptyResult):
        earthdata.EarthdataSource(ENTRY, tmp_path).fetch({"bbox": [0, 0, 1, 1]})
