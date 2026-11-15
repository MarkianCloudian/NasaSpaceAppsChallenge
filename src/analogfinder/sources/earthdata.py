"""NASA Earthdata (CMR search + LP DAAC download via earthaccess), `route: earthdata` (T021).

Login, never interactive: `earthaccess.login(strategy="netrc")` when `~/.netrc` has an entry for
urs.earthdata.nasa.gov, else `strategy="environment"`: `EARTHDATA_TOKEN` (bearer token) or
`EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`. Before that, a gitignored `.env` file in the current
directory or the repository root is read into the environment (existing variables win), so the
token can live in `<repo>/.env` as `EARTHDATA_TOKEN=<token>`. Credential values are never logged.

Search goes to the entry's `collection` (CMR concept id) when present, else `short_name` (request
or entry `dataset`) + `version` (request or entry `dataset_version`). Request keys:
`temporal: [start, end]` (ISO dates), `bounding_box` (or `bbox`): `[w, s, e, n]`,
`granule_ids: [...]` (download only these GranuleURs of the search result).

`search(request)` -> list of dicts `{granule_id, cloud, size_mb, links, granule}` (no download;
CMR search is anonymous). `fetch(request)` downloads every data file of the matching granules
into the cache directory and writes `granules.json`; no granule -> `EmptyResult`.
`probe()` checks the CMR collection anonymously and reports `login_present` without downloading.
"""

from __future__ import annotations

import json
import logging
import netrc
import os
from pathlib import Path

import requests

from ..errors import SourceError
from .base import EmptyResult, ProbeResult, Source, TransientError, register_adapter, with_retries

log = logging.getLogger("analogfinder.sources.earthdata")

EDL_HOST = "urs.earthdata.nasa.gov"
REPO_ROOT = Path(__file__).resolve().parents[3]
CRED_VARS = ("EARTHDATA_TOKEN", "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD")


def load_dotenv(paths=None) -> list[str]:
    """Read KEY=VALUE lines of `.env` files into os.environ (existing variables win).

    Returns the names (never the values) of the variables that were set."""
    if paths is None:
        paths = [Path.cwd() / ".env", REPO_ROOT / ".env"]
    seen, loaded = set(), []
    for p in paths:
        p = Path(p).resolve()
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if key and value and key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded


def netrc_has_edl(path=None) -> bool:
    try:
        return netrc.netrc(path).authenticators(EDL_HOST) is not None
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        return False


def credentials_present() -> bool:
    load_dotenv()
    env = os.environ
    token = bool(env.get("EARTHDATA_TOKEN"))
    pair = bool(env.get("EARTHDATA_USERNAME") and env.get("EARTHDATA_PASSWORD"))
    return token or pair or netrc_has_edl()


class _Login:
    done = False


def login(api) -> None:
    """Authenticate earthaccess once per process; raise SourceError when no credentials work."""
    if _Login.done:
        return
    load_dotenv()
    strategies = (["netrc"] if netrc_has_edl() else []) + ["environment"]
    errors = []
    for strategy in strategies:
        try:
            auth = api.login(strategy=strategy)
        except Exception as exc:  # LoginStrategyUnavailable / LoginAttemptFailure
            errors.append(f"{strategy}: {type(exc).__name__}: {exc}")
            continue
        if getattr(auth, "authenticated", False):
            _Login.done = True
            log.info("Earthdata login ok (strategy %s)", strategy)
            return
        errors.append(f"{strategy}: not authenticated")
    raise SourceError(
        "Earthdata login failed; put EARTHDATA_TOKEN=<token> in the repository .env file "
        "or add urs.earthdata.nasa.gov to ~/.netrc (" + "; ".join(errors) + ")"
    )


def _umm(g) -> dict:
    try:
        return g["umm"]
    except (KeyError, TypeError):
        return getattr(g, "umm", {}) or {}


def describe(g) -> dict:
    u = _umm(g)
    try:
        size = float(g.size())
    except Exception:  # noqa: BLE001 - size is informative only
        size = None
    cloud = u.get("CloudCover")
    return {
        "granule_id": u.get("GranuleUR"),
        "cloud": float(cloud) if isinstance(cloud, int | float) else None,
        "size_mb": size,
        "links": list(g.data_links()),
        "granule": g,
    }


@register_adapter("earthdata")
class EarthdataSource(Source):
    """CMR granule search and authenticated download through earthaccess."""

    def __init__(self, entry: dict, data_dir, sleep=None, api=None):
        if sleep is None:
            super().__init__(entry, data_dir)
        else:
            super().__init__(entry, data_dir, sleep=sleep)
        self._api = api

    @property
    def api(self):
        if self._api is None:
            import earthaccess

            self._api = earthaccess
        return self._api

    def query(self, request: dict) -> dict:
        kw: dict = {}
        if self.entry.get("collection") and "short_name" not in request:
            kw["concept_id"] = self.entry["collection"]
        else:
            kw["short_name"] = request.get("short_name", self.entry["dataset"])
            kw["version"] = request.get("version", self.entry["dataset_version"])
        if request.get("temporal"):
            kw["temporal"] = tuple(request["temporal"])
        bbox = request.get("bounding_box") or request.get("bbox")
        if bbox:
            kw["bounding_box"] = tuple(float(v) for v in bbox)
        return kw

    def probe(self) -> ProbeResult:
        login_ok = credentials_present()
        url = self.entry["endpoint"].rstrip("/") + "/collections.json"
        params = (
            {"concept_id": self.entry["collection"]}
            if self.entry.get("collection")
            else {"short_name": self.entry["dataset"]}
        )
        try:
            r = requests.get(url, params=params, timeout=30)
            ok = r.status_code < 400 and bool(r.json().get("feed", {}).get("entry"))
            return ProbeResult(
                ok, login_ok, None if ok else f"HTTP {r.status_code} / no collection"
            )
        except (requests.RequestException, ValueError) as e:
            return ProbeResult(False, login_ok, str(e))

    def search(self, request: dict) -> list[dict]:
        kw = self.query(request)

        def run():
            self.limiter.acquire()
            try:
                return self.api.search_data(**kw)
            except (requests.RequestException, OSError) as exc:
                raise TransientError(f"{self.source_id}: CMR search failed: {exc}") from exc

        found = [describe(g) for g in with_retries(run, self.retries, sleep=self.sleep)]
        found.sort(key=lambda d: d["granule_id"] or "")
        ids = request.get("granule_ids")
        if ids:
            wanted = set(ids)
            found = [d for d in found if d["granule_id"] in wanted]
        return found

    def _download(self, request: dict, target: Path) -> None:
        found = self.search(request)
        if not found:
            raise EmptyResult(f"{self.source_id}: no granules for {self.query(request)}")
        login(self.api)
        expected = sum(len(d["links"]) for d in found)
        total_mb = sum(d["size_mb"] or 0 for d in found)
        log.info(
            "%s: downloading %d granule(s), %d file(s), ~%.0f MB",
            self.source_id,
            len(found),
            expected,
            total_mb,
        )
        try:
            paths = self.api.download(
                [d["granule"] for d in found],
                local_path=str(target),
                threads=4,
                show_progress=False,
                pqdm_kwargs={"exception_behaviour": "immediate"},
            )
        except Exception as exc:  # network errors surface as plain exceptions from pqdm
            raise TransientError(f"{self.source_id}: download failed: {exc}") from exc
        got = [Path(p) for p in paths if p and Path(p).is_file()]
        if len(got) < expected:
            raise TransientError(f"{self.source_id}: downloaded {len(got)} of {expected} files")
        (target / "granules.json").write_text(
            json.dumps([{k: v for k, v in d.items() if k != "granule"} for d in found], indent=1),
            encoding="utf-8",
        )
