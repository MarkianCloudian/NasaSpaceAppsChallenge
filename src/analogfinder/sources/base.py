"""Uniform source access: probe, cached fetch, rate limit, retries, fallback (plan A4, T018).

A source adapter is built from one `config/sources.json` entry. `fetch(request)` returns a
FetchResult (contracts/internal-api.md) whose path is the complete cache directory for that
request; a complete directory is returned without network.

Adapters for the routes `http`, `stac`, `earthdata`, `rest` (tasks T019–T022) register
themselves with `@register_adapter("<route>")`; `manual` sources are built in and never
fetchable. `SourceRegistry.from_config(sources_config, data_dir)` (alias `registry`) builds
one adapter per entry.
"""

from __future__ import annotations

import abc
import importlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .. import storage
from ..errors import SourceError
from ..types import FetchResult

log = logging.getLogger("analogfinder.sources.base")


@dataclass
class ProbeResult:
    reachable: bool
    login_present: bool
    error: str | None = None


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
            sleep(2**attempt)


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
        return storage.cache_dir(
            self.data_dir, self.source_id, self.entry["dataset_version"], request
        )

    def fetch(self, request: dict) -> FetchResult:
        final = self.cache_path(request)
        if storage.is_complete(final):
            return FetchResult(final, self.source_id, None)

        def attempt():
            self.limiter.acquire()
            with storage.atomic_dir(
                final,
                manifest={
                    "source_id": self.source_id,
                    "dataset_version": self.entry["dataset_version"],
                },
            ) as tmp:
                storage.write_request(tmp, request)
                self._download(request, tmp)
            return final

        return FetchResult(
            with_retries(attempt, self.retries, sleep=self.sleep), self.source_id, None
        )


class ManualSource(Source):
    """`route: manual` — documented, hand-entered values; never fetchable."""

    def probe(self):
        return ProbeResult(reachable=True, login_present=True)

    def _download(self, request, target):
        raise SourceError(f"{self.source_id}: manual source cannot be fetched")

    def fetch(self, request):
        raise SourceError(f"{self.source_id}: manual source cannot be fetched")


ADAPTERS: dict[str, type[Source]] = {"manual": ManualSource}

# Modules whose import registers the adapter of each route. `SourceRegistry.from_config` imports
# them, so a real run sees every adapter without the caller importing them first.
ROUTE_MODULES: dict[str, str] = {
    "http": "analogfinder.sources.http",
    "stac": "analogfinder.sources.stac",
    "earthdata": "analogfinder.sources.earthdata",
    "rest": "analogfinder.sources.power",
}


def load_adapters() -> None:
    """Import every adapter module in ROUTE_MODULES (each registers itself)."""
    for route, module in ROUTE_MODULES.items():
        if route in ADAPTERS:
            continue
        try:
            importlib.import_module(module)
        except ImportError as e:  # route stays unregistered; `get` reports it per source
            log.warning("adapter for route %r not available: %s", route, e)


def register_adapter(route: str):
    """Class decorator: `@register_adapter("http")` makes the route available to registries."""

    def deco(cls):
        ADAPTERS[route] = cls
        return cls

    return deco


class SourceRegistry:
    """source_id -> adapter, built from config/sources.json."""

    def __init__(self, sources: dict[str, Source], missing: dict[str, str] | None = None):
        self._sources = dict(sources)
        self._missing = dict(missing or {})  # source_id -> route without a registered adapter

    @classmethod
    def from_config(cls, sources_config: dict, data_dir, adapters: dict | None = None):
        """`adapters` maps route -> adapter class (default: every adapter in ROUTE_MODULES)."""
        if adapters is None:
            load_adapters()
        table = ADAPTERS if adapters is None else adapters
        out, missing = {}, {}
        for e in sources_config["sources"]:
            adapter = table.get(e["route"])
            if adapter is None:
                missing[e["source_id"]] = e["route"]
            else:
                out[e["source_id"]] = adapter(e, data_dir)
        return cls(out, missing)

    def get(self, source_id: str) -> Source:
        if source_id in self._sources:
            return self._sources[source_id]
        if source_id in self._missing:
            route = self._missing[source_id]
            raise SourceError(f"{source_id}: no adapter registered for route {route!r} yet")
        raise SourceError(f"unknown source {source_id!r}")

    def __contains__(self, source_id: str) -> bool:
        return source_id in self._sources


registry = SourceRegistry.from_config


def fetch_with_fallback(
    registry: SourceRegistry,
    source_id: str,
    request: dict,
    coverage=None,
    min_coverage: float | None = None,
) -> FetchResult:
    """Fetch from `source_id`; switch to its `fallback` when (a) it still fails after retries,
    (b) the search is empty, or (c) `coverage(path) < min_coverage` (research D-022).
    The returned FetchResult names the source that actually served the data."""
    tried, current, errors = set(), source_id, []
    while current and current not in tried:
        tried.add(current)
        src = registry.get(current)
        try:
            res = src.fetch(request)
            cov = coverage(res.path) if coverage is not None else None
            if cov is None or min_coverage is None or cov >= min_coverage:
                return FetchResult(res.path, current, cov)
            errors.append(f"{current}: coverage {cov:.2f} below {min_coverage}")
        except EmptyResult:
            errors.append(f"{current}: no items for the requested area")
        except (TransientError, SourceError) as e:
            errors.append(f"{current}: {e}")
        current = src.entry.get("fallback")
    raise SourceError("; ".join(errors) or f"{source_id}: nothing fetched")
