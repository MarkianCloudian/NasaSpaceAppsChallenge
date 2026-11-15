"""NASA POWER regional climatology adapter, `route: rest` (plan A4, task T022, research D-008).

Verified against the live API (2026-11-15, see research.md "Verification results"): the regional
climatology endpoint accepts boxes of 2°–10° per side and **one parameter per request**. Larger
areas are tiled with `tile_bbox`; each (tile, parameter) is one HTTP request. Point requests are
deliberately not implemented (≈ 60 000 points ≈ 33 h at the rate limit): when regional
climatology is unavailable the registry `fallback` (ERA5, `gridded_netcdf`) is used instead.

Request dict: `{"bbox": [lon_min, lat_min, lon_max, lat_max], "parameters": [...]}` for ONE tile
(side ≤ MAX_TILE_DEG); `fetch_tiles` tiles an arbitrary bbox. Each parameter is stored as
`<PARAMETER>.json` (the raw GeoJSON FeatureCollection) in the cache directory.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import requests

from ..errors import SourceError
from ..types import FetchResult
from .base import EmptyResult, ProbeResult, Source, TransientError, register_adapter

log = logging.getLogger("analogfinder.sources.power")

MIN_TILE_DEG = 2.0
MAX_TILE_DEG = 10.0
COMMUNITY = "RE"
DEFAULT_PARAMETERS = (
    "T2M",
    "T2M_MIN",
    "T2M_MAX",
    "RH2M",
    "WS10M",
    "PRECTOTCORR",
    "ALLSKY_SFC_SW_DWN",
)
REGIONAL_PATH = "temporal/climatology/regional"
TIMEOUT_S = 120


def _split(lo: float, hi: float, limit_lo: float, limit_hi: float) -> list[tuple[float, float]]:
    span = hi - lo
    if span < MIN_TILE_DEG:  # POWER refuses < 2°: widen symmetrically, stay inside the globe
        lo = max(limit_lo, min(lo - (MIN_TILE_DEG - span) / 2, limit_hi - MIN_TILE_DEG))
        return [(lo, lo + MIN_TILE_DEG)]
    n = math.ceil(span / MAX_TILE_DEG - 1e-9)
    step = span / n  # equal parts: each in [MIN, MAX] since span >= 2
    return [(lo + i * step, lo + (i + 1) * step) for i in range(n)]


def tile_bbox(bbox) -> list[tuple[float, float, float, float]]:
    """Split `(lon_min, lat_min, lon_max, lat_max)` into tiles of 2°–10° per side."""
    w, s, e, n = (float(v) for v in bbox)
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise SourceError(f"invalid bbox {tuple(bbox)!r}")
    return [
        (x0, y0, x1, y1)
        for (y0, y1) in _split(s, n, -90, 90)
        for (x0, x1) in _split(w, e, -180, 180)
    ]


@register_adapter("rest")
class PowerSource(Source):
    """NASA POWER regional climatology (community RE, JSON)."""

    def __init__(self, entry: dict, data_dir, sleep=None, session=None):
        if sleep is None:
            super().__init__(entry, data_dir)
        else:
            super().__init__(entry, data_dir, sleep=sleep)
        self.session = session or requests.Session()

    @property
    def url(self) -> str:
        return self.entry["endpoint"].rstrip("/") + "/" + REGIONAL_PATH

    def probe(self) -> ProbeResult:
        try:
            r = self.session.get(self.entry["endpoint"], timeout=30)
            return ProbeResult(reachable=r.status_code < 500, login_present=True)
        except requests.RequestException as e:
            return ProbeResult(reachable=False, login_present=True, error=str(e))

    def fetch_tiles(self, bbox, parameters=DEFAULT_PARAMETERS) -> list[FetchResult]:
        """Tile `bbox` and fetch every tile (cached tiles make no HTTP request)."""
        return [
            self.fetch({"bbox": list(t), "parameters": list(parameters)}) for t in tile_bbox(bbox)
        ]

    def _params(self, bbox, parameter: str) -> dict:
        w, s, e, n = bbox
        return {
            "latitude-min": s,
            "latitude-max": n,
            "longitude-min": w,
            "longitude-max": e,
            "parameters": parameter,
            "community": COMMUNITY,
            "format": "JSON",
        }

    def _download(self, request: dict, target: Path) -> None:
        bbox = [float(v) for v in request["bbox"]]
        w, s, e, n = bbox
        if not (MIN_TILE_DEG <= e - w <= MAX_TILE_DEG and MIN_TILE_DEG <= n - s <= MAX_TILE_DEG):
            raise SourceError(
                f"{self.source_id}: tile must be {MIN_TILE_DEG}°–{MAX_TILE_DEG}° per side "
                "(use tile_bbox / fetch_tiles)"
            )
        for i, parameter in enumerate(request["parameters"]):
            if i:  # base.fetch already acquired a token for the first request
                self.limiter.acquire()
            try:
                r = self.session.get(
                    self.url, params=self._params(bbox, parameter), timeout=TIMEOUT_S
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                raise TransientError(str(exc)) from exc
            if r.status_code == 429 or r.status_code >= 500:
                raise TransientError(f"HTTP {r.status_code}")
            if r.status_code != 200:
                raise SourceError(f"{self.source_id}: HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            if not data.get("features"):
                raise EmptyResult(f"{self.source_id}: no POWER cells for {bbox} / {parameter}")
            (target / f"{parameter}.json").write_text(json.dumps(data), encoding="utf-8")
            log.info("fetched %s tile %s", parameter, bbox)
