"""NASA Earthdata adapter (`route: earthdata`, task T020).

Login: `~/.netrc` first, then env EARTHDATA_USERNAME / EARTHDATA_PASSWORD; never interactive.
CMR collection search is anonymous, so `probe()` needs no credentials and downloads nothing.

Request keys: `bounding_box` [west, south, east, north] (required), `temporal` [start, end]
(optional), `max_granules` (optional), `least_cloud` (optional: sort by UMM CloudCover
before keeping `max_granules`). Collection = entry `collection` (short name),
version = entry `dataset_version`.
"""
import netrc
import os
from pathlib import Path

from .base import EmptyResult, ProbeResult, Source, TransientError


def login_present() -> bool:
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        return True
    try:
        return netrc.netrc().authenticators("urs.earthdata.nasa.gov") is not None
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        return False


def _login():
    import earthaccess

    for strategy in ("netrc", "environment"):
        try:
            auth = earthaccess.login(strategy=strategy, persist=False)
            if auth is not None and getattr(auth, "authenticated", False):
                return auth
        except Exception:  # noqa: BLE001 — try next strategy
            continue
    return None


def _cloud_cover(granule) -> float:
    try:
        v = granule["umm"].get("CloudCover")
        return float(v) if v is not None else 101.0
    except (KeyError, TypeError, AttributeError, ValueError):
        return 101.0


class EarthdataSource(Source):
    def __init__(self, entry, data_dir, sleep=None, api=None):
        kwargs = {"sleep": sleep} if sleep else {}
        super().__init__(entry, data_dir, **kwargs)
        self._api = api  # injectable for tests (needs search_data, download, search_datasets)
        self._needs_login = api is None  # an injected fake API needs no login

    @property
    def api(self):
        if self._api is None:
            import earthaccess
            self._api = earthaccess
        return self._api

    @property
    def short_name(self) -> str:
        return self.entry.get("collection") or self.entry["dataset"]

    def probe(self) -> ProbeResult:
        has_login = login_present()
        try:
            found = self.api.search_datasets(short_name=self.short_name,
                                             version=self.entry["dataset_version"], count=1)
            reachable = bool(found)
            err = None if reachable else f"collection {self.short_name} not found in CMR"
        except Exception as e:  # noqa: BLE001
            reachable, err = False, f"CMR search failed: {e}"
        return ProbeResult(reachable=reachable, login_present=has_login, error=err)

    def search(self, request: dict):
        kw = {"short_name": self.short_name, "version": self.entry["dataset_version"],
              "bounding_box": tuple(request["bounding_box"])}
        if request.get("temporal"):
            kw["temporal"] = tuple(request["temporal"])
        limit = int(request["max_granules"]) if request.get("max_granules") else None
        if limit and not request.get("least_cloud"):
            kw["count"] = limit
        try:
            found = list(self.api.search_data(**kw))
        except Exception as e:  # noqa: BLE001 — network problems are transient
            raise TransientError(f"CMR search failed: {e}") from e
        if request.get("least_cloud"):
            found.sort(key=_cloud_cover)
        return found[:limit] if limit else found

    def _download(self, request: dict, target: Path) -> None:
        granules = self.search(request)
        if not granules:
            raise EmptyResult(f"{self.short_name}: no granules for {request['bounding_box']}")
        if self._needs_login:
            if _login() is None:
                from ..errors import SourceError
                raise SourceError(f"{self.source_id}: Earthdata login missing (~/.netrc or EARTHDATA_* env)")
            self._needs_login = False
        try:
            files = self.api.download(granules, local_path=str(target))
        except Exception as e:  # noqa: BLE001
            raise TransientError(f"download failed: {e}") from e
        if not files:
            raise TransientError("download returned no files")
