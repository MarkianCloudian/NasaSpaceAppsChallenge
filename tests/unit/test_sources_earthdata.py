"""`route: earthdata` adapter (T021) with a fake earthaccess API; online login/search check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analogfinder.errors import SourceError
from analogfinder.sources import earthdata as ed
from analogfinder.sources.base import EmptyResult, TransientError


class Granule(dict):
    def __init__(self, gid, cloud=None, files=("a.nc",)):
        super().__init__(umm={"GranuleUR": gid, "CloudCover": cloud})
        self.files = [f"https://data.example/{gid}/{f}" for f in files]

    def data_links(self):
        return self.files

    def size(self):
        return 1.5


class FakeApi:
    def __init__(self, granules, authenticated=True, drop=0):
        self.granules, self.authenticated, self.drop = granules, authenticated, drop
        self.searches, self.logins, self.downloaded = [], [], []

    def login(self, strategy):
        self.logins.append(strategy)
        if strategy == "netrc":
            raise RuntimeError("LoginStrategyUnavailable")
        return type("Auth", (), {"authenticated": self.authenticated})()

    def search_data(self, **kw):
        self.searches.append(kw)
        return list(self.granules)

    def download(self, granules, local_path, **kw):
        paths = []
        for g in granules:
            for link in g.data_links():
                p = Path(local_path) / link.rsplit("/", 1)[1]
                p.write_text("x")
                paths.append(p)
        self.downloaded.extend(paths)
        return paths[: len(paths) - self.drop]


ENTRY = {
    "source_id": "fx-ed",
    "dataset": "MOD11C3",
    "dataset_version": "061",
    "route": "earthdata",
    "endpoint": "https://cmr.earthdata.nasa.gov/search/",
    "collection": "C123-LPCLOUD",
    "rate_limit": {"requests": 100, "per_seconds": 1},
    "retries": 0,
}


@pytest.fixture(autouse=True)
def no_creds(monkeypatch, tmp_path):
    for k in ed.CRED_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.netrc
    monkeypatch.setattr(ed, "REPO_ROOT", tmp_path)  # no repository .env
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ed._Login, "done", False)


def _src(tmp_path, api):
    return ed.EarthdataSource(ENTRY, tmp_path / "data", sleep=lambda s: None, api=api)


def test_load_dotenv_sets_missing_only(tmp_path, monkeypatch):
    f = tmp_path / "x.env"
    f.write_text('# c\nEARTHDATA_TOKEN="abc"\nexport OTHER=1\nKEEP=new\nbad line\n')
    monkeypatch.setenv("KEEP", "old")
    monkeypatch.delenv("OTHER", raising=False)
    loaded = ed.load_dotenv([f])
    assert sorted(loaded) == ["EARTHDATA_TOKEN", "OTHER"]
    import os

    assert os.environ["EARTHDATA_TOKEN"] == "abc" and os.environ["KEEP"] == "old"


def test_probe_without_credentials(tmp_path, monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"feed": {"entry": [{"id": "C123-LPCLOUD"}]}}

    monkeypatch.setattr(ed.requests, "get", lambda *a, **k: R())
    p = _src(tmp_path, FakeApi([])).probe()
    assert p.reachable and p.login_present is False


def test_query_uses_concept_id_or_short_name(tmp_path):
    s = _src(tmp_path, FakeApi([]))
    q = s.query({"bounding_box": [1, 2, 3, 4], "temporal": ["2023-01-01", "2023-12-31"]})
    assert q == {
        "concept_id": "C123-LPCLOUD",
        "bounding_box": (1.0, 2.0, 3.0, 4.0),
        "temporal": ("2023-01-01", "2023-12-31"),
    }
    q = s.query({"short_name": "MOD11C3", "version": "061"})
    assert q == {"short_name": "MOD11C3", "version": "061"}


def test_fetch_downloads_selected_granules(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "t")
    api = FakeApi([Granule("G2", 5, ("m.nc", "u.nc")), Granule("G1", 50)])
    s = _src(tmp_path, api)
    assert [g["granule_id"] for g in s.search({"bbox": [0, 0, 1, 1]})] == ["G1", "G2"]
    res = s.fetch({"bounding_box": [0, 0, 1, 1], "granule_ids": ["G2"]})
    assert sorted(p.name for p in res.path.glob("*.nc")) == ["m.nc", "u.nc"]
    meta = json.loads((res.path / "granules.json").read_text())
    assert [m["granule_id"] for m in meta] == ["G2"] and meta[0]["cloud"] == 5.0
    assert api.logins == ["environment"]  # no ~/.netrc -> straight to the token
    n = len(api.searches)
    s.fetch({"bounding_box": [0, 0, 1, 1], "granule_ids": ["G2"]})
    assert len(api.searches) == n  # cached: no new search or download


def test_empty_search_and_login_failure(tmp_path, monkeypatch):
    with pytest.raises(EmptyResult):
        _src(tmp_path, FakeApi([])).fetch({"bbox": [0, 0, 1, 1]})
    with pytest.raises(SourceError, match="Earthdata login failed"):
        _src(tmp_path, FakeApi([Granule("G1")], authenticated=False)).fetch({"bbox": [0, 0, 1, 1]})


def test_missing_files_are_transient(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "t")
    with pytest.raises(TransientError, match="1 of 2"):
        _src(tmp_path, FakeApi([Granule("G1", files=("a", "b"))], drop=1)).fetch(
            {"bbox": [0, 0, 1, 1]}
        )


@pytest.mark.online
def test_online_token_login_and_search(monkeypatch):
    """Needs EARTHDATA_TOKEN in the repository .env (or ~/.netrc)."""
    root = Path(__file__).resolve().parents[2]
    monkeypatch.undo()  # real HOME, cwd and environment
    ed._Login.done = False
    ed.load_dotenv([root / ".env"])
    if not ed.credentials_present():
        pytest.skip("no Earthdata credentials")
    from analogfinder import config
    from analogfinder.sources.base import SourceRegistry

    reg = SourceRegistry.from_config(config.load_sources(root / "config"), root / "data")
    src = reg.get("modis-mcd12c1")
    assert src.probe().reachable
    found = src.search({"temporal": ["2023-01-01", "2023-12-31"]})
    assert len(found) == 1 and found[0]["links"]
    import earthaccess

    ed.login(earthaccess)
    assert ed._Login.done
