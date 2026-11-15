"""`route: http` adapter (T019) against a local http.server; no internet."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from analogfinder import config, storage
from analogfinder.sources import base
from analogfinder.sources.base import TransientError
from analogfinder.sources.http import HttpSource, file_name

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB
HITS: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep test output quiet
        pass

    def _send(self, body: bool):
        HITS.append(f"{self.command} {self.path}")
        if self.path.startswith("/broken"):
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        if body:
            self.wfile.write(PAYLOAD)

    def do_GET(self):
        self._send(True)

    def do_HEAD(self):
        self._send(False)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _entry(url):
    return {
        "source_id": "fx-file",
        "dataset_version": "1",
        "route": "http",
        "endpoint": url,
        "rate_limit": {"requests": 100, "per_seconds": 1},
        "retries": 2,
    }


def test_downloads_once_then_reuses(server, tmp_path):
    HITS.clear()
    src = HttpSource(_entry(f"{server}/dem.tif"), tmp_path, sleep=lambda s: None)
    r1 = src.fetch({"file": "dem.tif"})
    assert (r1.path / "dem.tif").read_bytes() == PAYLOAD
    assert storage.is_complete(r1.path) and not list(r1.path.glob("*.part"))
    rec = json.loads((r1.path / "request.json").read_text())
    assert rec["sha256"] == hashlib.sha256(PAYLOAD).hexdigest() and rec["bytes"] == len(PAYLOAD)
    n = len(HITS)
    r2 = src.fetch({"file": "dem.tif"})
    assert r2.path == r1.path and len(HITS) == n  # second call: no request


def test_server_error_is_retried_then_raised(server, tmp_path):
    HITS.clear()
    src = HttpSource(_entry(f"{server}/broken"), tmp_path, sleep=lambda s: None)
    with pytest.raises(TransientError):
        src.fetch({"file": "x.tif"})
    assert len(HITS) == 3  # 1 try + 2 retries


def test_probe(server, tmp_path):
    assert HttpSource(_entry(f"{server}/dem.tif"), tmp_path).probe().reachable
    assert not HttpSource(_entry(f"{server}/broken"), tmp_path).probe().reachable


def test_file_name_rules():
    assert file_name({}, "https://h/a/b/ETOPO.tif") == "ETOPO.tif"
    assert file_name({"file": "dem.tif"}, "https://h/x") == "dem.tif"
    with pytest.raises(Exception, match="plain name"):
        file_name({"file": "../evil"}, "https://h/x")


def test_registry_registers_every_route():
    """A registry built from the real config has an adapter for every non-manual source."""
    reg = base.SourceRegistry.from_config(config.load_sources("config"), "data")
    assert reg._missing == {}
    assert type(reg.get("etopo-2022")).__name__ == "HttpSource"
    assert type(reg.get("nasadem-pc")).__name__ == "StacSource"
    assert type(reg.get("modis-mod11c3")).__name__ == "EarthdataSource"
    assert type(reg.get("nasa-power")).__name__ == "PowerSource"
