"""T020: probe without credentials; least-cloud selection; cached fetch via a fake API."""
from analogfinder.sources import earthdata
from analogfinder.sources.earthdata import EarthdataSource

ENTRY = {"source_id": "emit-l2b-min", "dataset": "EMIT L2B MIN", "collection": "EMITL2BMIN",
         "dataset_version": "002", "rate_limit": {"requests": 10, "per_seconds": 1}, "retries": 0}


class FakeAPI:
    def __init__(self, granules):
        self.granules, self.downloads = granules, 0

    def search_datasets(self, **kw):
        return [{"short_name": kw["short_name"]}]

    def search_data(self, **kw):
        return list(self.granules)

    def download(self, granules, local_path):
        self.downloads += 1
        out = []
        for g in granules:
            p = f"{local_path}/{g['name']}"
            open(p, "w").write("x")
            out.append(p)
        return out


def test_probe_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    monkeypatch.setenv("NETRC", str(tmp_path / "none"))
    monkeypatch.setattr(earthdata.netrc, "netrc", lambda *a: (_ for _ in ()).throw(FileNotFoundError()))
    r = EarthdataSource(ENTRY, tmp_path, api=FakeAPI([])).probe()
    assert r.login_present is False and r.reachable is True and r.error is None


def test_least_cloud_and_cache(tmp_path):
    gs = [{"name": f"g{i}", "umm": {"CloudCover": c}} for i, c in enumerate([80, 5, 40, None])]
    api = FakeAPI(gs)
    src = EarthdataSource(ENTRY, tmp_path, api=api)
    picked = src.search({"bounding_box": [0, 0, 1, 1], "max_granules": 2, "least_cloud": True})
    assert [g["name"] for g in picked] == ["g1", "g2"]
    req = {"bounding_box": [0, 0, 1, 1], "max_granules": 2, "least_cloud": True}
    p1 = src.fetch(req)
    p2 = src.fetch(req)
    assert p1 == p2 and api.downloads == 1 and sorted(x.name for x in p1.iterdir() if x.name.startswith("g")) == ["g1", "g2"]
