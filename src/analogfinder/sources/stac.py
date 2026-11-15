"""`route: stac` adapter (plan A4, task T020).

Request shape (all keys JSON-serialisable; `bbox` is [west, south, east, north]):

    {"bbox": [w, s, e, n],
     "assets": ["elevation"],        # optional; default: every asset of every item
     "download": false,              # false: record signed COG URLs for windowed reads
     "max_items": 100,               # optional
     "datetime": "2000-01-01/.."}    # optional

The cache directory gets `request.json` (the request plus a `resolved` list of items with the
chosen asset hrefs) and, when `download` is true, the asset files.
Planetary Computer endpoints are signed with `planetary_computer.sign_inplace`
(anonymous; `PC_SDK_SUBSCRIPTION_KEY` is picked up by the SDK from the environment).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests

from .. import storage
from ..errors import SourceError
from .base import EmptyResult, ProbeResult, Source, TransientError, register_adapter

log = logging.getLogger("analogfinder.sources.stac")

TIMEOUT_S = 60


def _is_planetary_computer(endpoint: str) -> bool:
    host = urlparse(endpoint).hostname or ""
    return host == "planetarycomputer.microsoft.com" or host.endswith(
        ".planetarycomputer.microsoft.com"
    )


def _transient(exc: Exception) -> bool:
    if isinstance(exc, requests.Timeout | requests.ConnectionError):
        return True
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    return status is not None and status >= 500


@register_adapter("stac")
class StacSource(Source):
    def __init__(self, entry: dict, data_dir, sleep=None):
        if sleep is None:
            super().__init__(entry, data_dir)
        else:
            super().__init__(entry, data_dir, sleep=sleep)
        self.endpoint = entry["endpoint"].rstrip("/")
        self.collection = entry["collection"]

    # -- helpers ---------------------------------------------------------------------------

    def _client(self):
        from pystac_client import Client

        modifier = None
        if _is_planetary_computer(self.endpoint):
            import planetary_computer

            modifier = planetary_computer.sign_inplace
        return Client.open(self.endpoint, modifier=modifier)

    def search(self, request: dict) -> list:
        """Signed pystac items of the collection intersecting `request['bbox']`."""
        try:
            search = self._client().search(
                collections=[self.collection],
                bbox=request["bbox"],
                datetime=request.get("datetime"),
                max_items=request.get("max_items", 100),
            )
            return list(search.items())
        except Exception as e:
            if _transient(e):
                raise TransientError(str(e)) from e
            raise SourceError(f"{self.source_id}: STAC search failed: {e}") from e

    # -- Source API ------------------------------------------------------------------------

    def probe(self) -> ProbeResult:
        url = f"{self.endpoint}/collections/{self.collection}"
        try:
            r = requests.get(url, timeout=TIMEOUT_S)
            ok = r.status_code == 200
            err = None if ok else f"HTTP {r.status_code} from {url}"
        except requests.RequestException as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        login = self.entry.get("login", "none")
        present = login == "none" or (
            login == "api_key" and bool(os.environ.get("PC_SDK_SUBSCRIPTION_KEY"))
        )
        return ProbeResult(reachable=ok, login_present=present, error=err)

    def _download(self, request: dict, target: Path) -> None:
        items = self.search(request)
        if not items:
            raise EmptyResult(f"{self.source_id}: no items for bbox {request['bbox']}")
        wanted = request.get("assets")
        resolved = []
        for item in items:
            keys = list(wanted) if wanted else list(item.assets)
            missing = [k for k in keys if k not in item.assets]
            if missing:
                raise SourceError(f"{self.source_id}: item {item.id} lacks assets {missing}")
            resolved.append({"id": item.id, "assets": {k: item.assets[k].href for k in keys}})
        if request.get("download", False):
            for entry in resolved:
                for key, href in list(entry["assets"].items()):
                    name = Path(urlparse(href).path).name or f"{entry['id']}-{key}"
                    dest = target / entry["id"] / name
                    self._download_file(href, dest)
                    entry["assets"][key] = str(dest.relative_to(target))
        # Signed URLs expire: they are recorded for windowed reads, not for long-term reuse.
        storage.write_request(target, {**request, "resolved": resolved})

    def _download_file(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with requests.get(url, stream=True, timeout=TIMEOUT_S) as r:
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    shutil.copyfileobj(r.raw, fh)
        except requests.RequestException as e:
            if _transient(e):
                raise TransientError(str(e)) from e
            raise SourceError(f"{self.source_id}: download of {url} failed: {e}") from e
