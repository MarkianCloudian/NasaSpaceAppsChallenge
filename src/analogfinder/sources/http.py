"""Plain HTTP(S) file download, `route: http` (plan A4, task T019).

Request dict: `{"url": <file URL>, "file": <local file name>}`; both optional — `url` defaults to
the entry's `endpoint`, `file` to the last path segment of the URL. The file is streamed into the
cache directory (`<file>.part`, renamed when complete), its size is checked against
`Content-Length` and its sha256 is recorded in `request.json` next to the request. Resuming an
interrupted download is not supported: a retry starts again (base `with_retries`).

`probe()` = HEAD on the endpoint (falling back to a one-byte ranged GET when HEAD is refused).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from ..errors import SourceError
from .base import ProbeResult, Source, TransientError, register_adapter

log = logging.getLogger("analogfinder.sources.http")

CHUNK = 8 * 1024 * 1024
CONNECT_TIMEOUT_S = 30
DEFAULT_READ_TIMEOUT_S = 60  # between received bytes, not for the whole file
LOG_EVERY_BYTES = 256 * 1024 * 1024


def file_name(request: dict, url: str) -> str:
    name = request.get("file") or Path(urlparse(url).path).name or "download"
    if "/" in name or "\\" in name or name in (".", ".."):
        raise SourceError(f"http: request file name must be a plain name, got {name!r}")
    return name


@register_adapter("http")
class HttpSource(Source):
    """Streams one file per request into the download cache."""

    def __init__(self, entry: dict, data_dir, sleep=None, session=None):
        if sleep is None:
            super().__init__(entry, data_dir)
        else:
            super().__init__(entry, data_dir, sleep=sleep)
        self.session = session or requests.Session()
        self.read_timeout = float(entry.get("timeout_s", DEFAULT_READ_TIMEOUT_S))

    def probe(self) -> ProbeResult:
        url = self.entry["endpoint"]
        try:
            r = self.session.head(url, allow_redirects=True, timeout=CONNECT_TIMEOUT_S)
            if r.status_code in (403, 405, 501):  # some servers refuse HEAD
                r = self.session.get(
                    url,
                    headers={"Range": "bytes=0-0"},
                    stream=True,
                    allow_redirects=True,
                    timeout=CONNECT_TIMEOUT_S,
                )
                r.close()
            ok = r.status_code < 400
            return ProbeResult(ok, True, None if ok else f"HTTP {r.status_code}")
        except requests.RequestException as e:
            return ProbeResult(False, True, str(e))

    def _download(self, request: dict, target: Path) -> None:
        url = request.get("url") or self.entry["endpoint"]
        name = file_name(request, url)
        part = target / f"{name}.part"
        digest = hashlib.sha256()
        size = 0
        t0 = time.monotonic()
        try:
            with self.session.get(
                url,
                stream=True,
                allow_redirects=True,
                timeout=(CONNECT_TIMEOUT_S, self.read_timeout),
            ) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise TransientError(f"{self.source_id}: HTTP {r.status_code} for {url}")
                if r.status_code != 200:
                    raise SourceError(f"{self.source_id}: HTTP {r.status_code} for {url}")
                expected = r.headers.get("Content-Length")
                expected = int(expected) if expected and expected.isdigit() else None
                next_log = LOG_EVERY_BYTES
                with open(part, "wb") as fh:
                    for chunk in r.iter_content(CHUNK):
                        fh.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        if size >= next_log:
                            log.info(
                                "%s: %.0f MB%s",
                                self.source_id,
                                size / 1e6,
                                f" of {expected / 1e6:.0f} MB" if expected else "",
                            )
                            next_log += LOG_EVERY_BYTES
        except (
            requests.Timeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            raise TransientError(f"{self.source_id}: {exc}") from exc
        if expected is not None and size != expected:
            raise TransientError(f"{self.source_id}: got {size} of {expected} bytes from {url}")
        part.rename(target / name)
        record = {**request, "url": url, "file": name, "bytes": size, "sha256": digest.hexdigest()}
        (target / "request.json").write_text(
            json.dumps(record, sort_keys=True, indent=1), encoding="utf-8"
        )
        log.info(
            "%s: downloaded %s (%.1f MB) in %.0f s",
            self.source_id,
            name,
            size / 1e6,
            time.monotonic() - t0,
        )
