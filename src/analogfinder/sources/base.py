"""Uniform source access: probe, cached fetch, rate limit, retries, fallback (plan A4, T017).

A source adapter is built from one `config/sources.json` entry. `fetch(request)` returns the
complete cache directory for that request; a complete directory is returned without network.
"""
import abc
import time
from dataclasses import dataclass
from pathlib import Path

from .. import storage
from ..errors import SourceError


@dataclass
class ProbeResult:
    reachable: bool
    login_present: bool
    error: str | None = None


@dataclass
class FetchResult:
    path: Path
    source_id: str          # the source that actually served the data (may be a fallback)
    used_fallback: bool


class EmptyResult(Exception):
    """The search returned no items/granules for the requested area."""


class TransientError(Exception):
    """Timeout or HTTP 5xx: worth retrying."""


class RateLimiter:
    """Token bucket: at most `requests` calls per `per_seconds`."""

    def __init__(self, requests: int, per_seconds: float, clock=time.monotonic, sleep=time.sleep):
        self.capacity = requests
        self.rate = requests / per_seconds
        self.tokens = float(requests)
        self.clock, self.sleep = clock, sleep
        self.last = clock()

    def acquire(self):
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens < 1:
            wait = (1 - self.tokens) / self.rate
            self.sleep(wait)
            self.last = self.clock()
            self.tokens = 1.0
        self.tokens -= 1


def with_retries(fn, retries: int, sleep=time.sleep):
    """Call fn(); retry only TransientError with backoff 1 s, 2 s, 4 s…"""
    for attempt in range(retries + 1):
        try:
            return fn()
        except TransientError:
            if attempt == retries:
                raise
            sleep(2 ** attempt)


class Source(abc.ABC):
    def __init__(self, entry: dict, data_dir, sleep=time.sleep):
        self.entry = entry
        self.source_id = entry["source_id"]
        self.data_dir = Path(data_dir)
        rl = entry["rate_limit"]
        self.limiter = RateLimiter(rl["requests"], rl["per_seconds"], sleep=sleep)
        self.retries = entry.get("retries", 3)
        self.sleep = sleep

    @abc.abstractmethod
    def probe(self) -> ProbeResult: ...

    @abc.abstractmethod
    def _download(self, request: dict, target: Path) -> None:
        """Write the files for `request` into `target`; raise EmptyResult / TransientError."""

    def cache_path(self, request: dict) -> Path:
        return storage.cache_dir(self.data_dir, self.source_id, self.entry["dataset_version"], request)

    def fetch(self, request: dict) -> Path:
        final = self.cache_path(request)
        if storage.is_complete(final):
            return final

        def attempt():
            self.limiter.acquire()
            with storage.atomic_dir(final, manifest={"source_id": self.source_id,
                                                     "dataset_version": self.entry["dataset_version"]}) as tmp:
                storage.write_request(tmp, request)
                self._download(request, tmp)
            return final

        return with_retries(attempt, self.retries, sleep=self.sleep)


class ManualSource(Source):
    """`route: manual` — documented, hand-entered values; never fetchable."""

    def probe(self):
        return ProbeResult(reachable=True, login_present=True)

    def _download(self, request, target):
        raise SourceError(f"{self.source_id}: manual source cannot be fetched")

    def fetch(self, request):
        raise SourceError(f"{self.source_id}: manual source cannot be fetched")


def registry(sources_config: dict, data_dir, adapters: dict | None = None) -> dict:
    """source_id -> adapter instance. `adapters` maps route -> class (defaults below)."""
    if adapters is None:
        from .earthdata import EarthdataSource
        adapters = {"earthdata": EarthdataSource, "manual": ManualSource}
    out = {}
    for e in sources_config["sources"]:
        cls = adapters.get(e["route"])
        if cls is not None:
            out[e["source_id"]] = cls(e, data_dir)
    return out


def fetch_with_fallback(sources: dict, source_id: str, request: dict,
                        coverage=None, min_coverage: float | None = None) -> FetchResult:
    """Fetch from `source_id`; switch to its `fallback` when (a) it still fails after retries,
    (b) the search is empty, or (c) `coverage(path) < min_coverage` (research D-022)."""
    tried, current, errors = set(), source_id, []
    while current and current not in tried:
        tried.add(current)
        src = sources[current]
        try:
            path = src.fetch(request)
            if coverage is None or min_coverage is None or coverage(path) >= min_coverage:
                return FetchResult(path, current, current != source_id)
            errors.append(f"{current}: coverage below {min_coverage}")
        except EmptyResult:
            errors.append(f"{current}: no items for the requested area")
        except (TransientError, SourceError) as e:
            errors.append(f"{current}: {e}")
        current = src.entry.get("fallback")
    raise SourceError("; ".join(errors) or f"{source_id}: nothing fetched")
