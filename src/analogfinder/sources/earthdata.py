"""`route: earthdata` adapter — NASA Earthdata via `earthaccess` (plan A4, task T021).

Login never prompts: `strategy="netrc"` first, then `strategy="environment"`
(`EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`). `probe()` never downloads; CMR collection
search is anonymous, so reachability is checked without credentials.

Request keys (the cache key, see `storage.cache_dir`):
  `temporal`  — optional `[start, end]` ISO dates;
  `bbox`      — optional `[west, south, east, north]` in degrees.
"""

from __future__ import annotations

import logging
from pathlib import Path

import earthaccess

from ..errors import SourceError
from .base import EmptyResult, ProbeResult, Source, TransientError, register_adapter

log = logging.getLogger("analogfinder.sources.earthdata")

_STRATEGIES = ("netrc", "environment")


def _login():
    """Return an authenticated earthaccess Auth, or None. Never prompts interactively."""
    for strategy in _STRATEGIES:
        try:
            auth = earthaccess.login(strategy=strategy)
        except Exception as e:  # earthaccess raises on missing credentials
            log.debug("earthdata login via %s failed: %s", strategy, e)
            continue
        if auth is not None and getattr(auth, "authenticated", False):
            return auth
    return None


@register_adapter("earthdata")
class EarthdataSource(Source):
    def probe(self) -> ProbeResult:
        login_present = _login() is not None
        try:
            self.limiter.acquire()
            earthaccess.search_datasets(
                short_name=self.entry["collection"],
                version=self.entry["dataset_version"],
                count=1,
            )
            return ProbeResult(reachable=True, login_present=login_present)
        except Exception as e:
            return ProbeResult(reachable=False, login_present=login_present, error=str(e))

    def _download(self, request: dict, target: Path) -> None:
        if _login() is None:
            raise SourceError(
                f"{self.source_id}: NASA Earthdata login missing — add a ~/.netrc entry for "
                "urs.earthdata.nasa.gov or set EARTHDATA_USERNAME / EARTHDATA_PASSWORD"
            )
        kwargs = {
            "short_name": self.entry["collection"],
            "version": self.entry["dataset_version"],
        }
        if request.get("temporal"):
            kwargs["temporal"] = tuple(request["temporal"])
        if request.get("bbox"):
            kwargs["bounding_box"] = tuple(request["bbox"])
        try:
            granules = earthaccess.search_data(**kwargs)
        except Exception as e:
            raise TransientError(f"{self.source_id}: CMR search failed: {e}") from e
        if not granules:
            raise EmptyResult(f"{self.source_id}: no granules for {request}")
        try:
            files = earthaccess.download(granules, str(target))
        except Exception as e:
            raise TransientError(f"{self.source_id}: download failed: {e}") from e
        if not files:
            raise TransientError(f"{self.source_id}: download returned no files")
