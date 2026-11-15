"""STAC API search + clipped COG download, `route: stac` (plan A4, task T020).

Request dict: `{"bbox": [west, south, east, north]}` in degrees (`bounding_box` is accepted as an
alias; other keys such as `"kind": "dem"` only make the cache key). Optional `"asset"` names the
item asset to read; otherwise the entry's `asset`, else the first asset (by key) whose roles
contain `data` and whose media type is a GeoTIFF.

`search(request)` lists the items of the entry's `collection` intersecting the bbox. `fetch`
reads, for every item, only the window covering the bbox from the (signed) COG with rasterio and
writes it as `<item id>.tif` into the cache directory, plus `items.json` (item ids, asset keys,
unsigned hrefs). No item or no overlapping pixels -> `EmptyResult` (the caller's fallback is used).

Planetary Computer endpoints are signed anonymously with `planetary_computer.sign_inplace`
(optional env `PC_SDK_SUBSCRIPTION_KEY` is read by that package). `probe()` = GET
`<endpoint>/collections/<collection>`.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import requests

from ..errors import SourceError
from .base import EmptyResult, ProbeResult, Source, TransientError, register_adapter

log = logging.getLogger("analogfinder.sources.stac")

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
}


def request_bbox(request: dict) -> tuple[float, float, float, float]:
    bbox = request.get("bbox") or request.get("bounding_box")
    if not bbox or len(bbox) != 4:
        raise SourceError(f"stac: request needs bbox [w, s, e, n], got {bbox!r}")
    w, s, e, n = (float(v) for v in bbox)
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise SourceError(f"stac: invalid bbox {bbox!r}")
    return w, s, e, n


def pick_asset(item, key: str | None = None):
    """(key, asset) to read from a STAC item."""
    if key:
        if key not in item.assets:
            raise SourceError(f"stac: item {item.id} has no asset {key!r}")
        return key, item.assets[key]
    for k in sorted(item.assets):
        a = item.assets[k]
        if "data" in (a.roles or []) and "tiff" in (a.media_type or ""):
            return k, a
    raise SourceError(f"stac: item {item.id} has no GeoTIFF data asset ({sorted(item.assets)})")


def clip_to_file(href: str, bbox, out: Path) -> bool:
    """Read the window of `href` covering `bbox` (lon/lat) and write it to `out` as GeoTIFF.
    Returns False when the raster does not overlap the bbox."""
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    with rasterio.Env(**GDAL_ENV), rasterio.open(href) as src:
        b = bbox
        if src.crs and src.crs.to_epsg() != 4326:
            b = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
        win = from_bounds(*b, transform=src.transform)
        c0 = max(int(math.floor(win.col_off + 1e-9)), 0)
        r0 = max(int(math.floor(win.row_off + 1e-9)), 0)
        c1 = min(int(math.ceil(win.col_off + win.width - 1e-9)), src.width)
        r1 = min(int(math.ceil(win.row_off + win.height - 1e-9)), src.height)
        if c1 <= c0 or r1 <= r0:
            return False
        window = Window(c0, r0, c1 - c0, r1 - r0)
        data = src.read(1, window=window)
        profile = {
            "driver": "GTiff",
            "width": window.width,
            "height": window.height,
            "count": 1,
            "dtype": data.dtype,
            "crs": src.crs,
            "transform": src.window_transform(window),
            "nodata": src.nodata,
            "compress": "deflate",
        }
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(data, 1)
    return True


@register_adapter("stac")
class StacSource(Source):
    """Search a STAC collection by bbox and download the clipped data assets."""

    def __init__(self, entry: dict, data_dir, sleep=None, client_factory=None, clipper=None):
        if sleep is None:
            super().__init__(entry, data_dir)
        else:
            super().__init__(entry, data_dir, sleep=sleep)
        self._client_factory = client_factory or self._open_client
        self._clip = clipper or clip_to_file
        self._client = None

    @property
    def signs(self) -> bool:
        return "planetarycomputer" in self.entry["endpoint"]

    def _open_client(self):
        import pystac_client

        modifier = None
        if self.signs:
            import planetary_computer

            modifier = planetary_computer.sign_inplace
        return pystac_client.Client.open(self.entry["endpoint"], modifier=modifier)

    def probe(self) -> ProbeResult:
        url = f"{self.entry['endpoint'].rstrip('/')}/collections/{self.entry['collection']}"
        try:
            r = requests.get(url, timeout=30)
            ok = r.status_code < 400
            return ProbeResult(ok, True, None if ok else f"HTTP {r.status_code}")
        except requests.RequestException as e:
            return ProbeResult(False, True, str(e))

    def search(self, request: dict) -> list:
        bbox = request_bbox(request)
        try:
            if self._client is None:
                self._client = self._client_factory()
            found = self._client.search(collections=[self.entry["collection"]], bbox=list(bbox))
            items = list(found.items())
        except (requests.RequestException, OSError) as exc:
            raise TransientError(f"{self.source_id}: STAC search failed: {exc}") from exc
        except Exception as exc:  # pystac_client.APIError and friends
            if "APIError" in type(exc).__name__:
                raise TransientError(f"{self.source_id}: STAC search failed: {exc}") from exc
            raise
        return sorted(items, key=lambda i: i.id)

    def _download(self, request: dict, target: Path) -> None:
        bbox = request_bbox(request)
        items = self.search(request)
        if not items:
            raise EmptyResult(f"{self.source_id}: no items for bbox {list(bbox)}")
        key = request.get("asset") or self.entry.get("asset")
        written = []
        for item in items:
            akey, asset = pick_asset(item, key)
            out = target / f"{item.id}.tif"
            try:
                ok = self._clip(asset.href, bbox, out)
            except Exception as exc:  # rasterio / GDAL network errors
                if "RasterioIOError" in type(exc).__name__ or isinstance(exc, OSError):
                    raise TransientError(f"{self.source_id}: reading {item.id}: {exc}") from exc
                raise
            if ok:
                written.append({"id": item.id, "asset": akey, "href": asset.href.split("?")[0]})
        if not written:
            raise EmptyResult(f"{self.source_id}: no pixels of {len(items)} items in {list(bbox)}")
        (target / "items.json").write_text(
            json.dumps({"collection": self.entry["collection"], "items": written}, indent=1),
            encoding="utf-8",
        )
        log.info("%s: %d item(s) clipped to %s", self.source_id, len(written), list(bbox))
