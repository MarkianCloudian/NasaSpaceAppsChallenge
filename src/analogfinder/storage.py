"""Content-identified, never-overwritten storage (plan A3, research D-002/D-011)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import secrets
from pathlib import Path

COMPLETE = "_COMPLETE"


def _check(obj):
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("non-finite float in fingerprinted object")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError(f"non-string key {k!r} in fingerprinted object")
            _check(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _check(v)
    elif not (obj is None or isinstance(obj, (str, int, bool))):
        raise TypeError(f"cannot fingerprint {type(obj).__name__}")


def canonical_json(obj) -> str:
    """Plain JSON: sorted keys, separators (",", ":"), floats via repr (json's default), UTF-8.

    1 and 1.0 stay different ("1" vs "1.0"); NaN/inf and non-JSON types are rejected.
    """
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:16]


def is_complete(path) -> bool:
    return (Path(path) / COMPLETE).is_file()


@contextlib.contextmanager
def atomic_dir(final_path, manifest: dict | None = None):
    """Build into `<final>.partial-<random>`; on success rename and write `_COMPLETE`.

    On an exception the partial directory is left for `clean` and never renamed.
    """
    final = Path(final_path)
    if is_complete(final):
        raise FileExistsError(f"complete directory already exists: {final}")
    if final.exists():
        raise FileExistsError(f"incomplete directory in the way: {final} (run `analog clean`)")
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(f"{final.name}.partial-{secrets.token_hex(4)}")
    partial.mkdir()
    yield partial
    os.replace(partial, final)
    (final / COMPLETE).write_text(
        json.dumps(manifest or {}, sort_keys=True, indent=1), encoding="utf-8"
    )


def cache_dir(data_dir, source_id: str, dataset_version: str, request: dict) -> Path:
    """`data/cache/<source_id>/<dataset_version>/<fingerprint(request)>/` (not created)."""
    return Path(data_dir) / "cache" / source_id / dataset_version / fingerprint(request)


def write_request(directory, request: dict) -> None:
    (Path(directory) / "request.json").write_text(canonical_json(request), encoding="utf-8")


def stage_dir(data_dir, stage: str, fp: str) -> Path:
    """`data/stages/<stage>/<fingerprint>/` (research D-011); not created."""
    return Path(data_dir) / "stages" / stage / fp


def grid_dir(data_dir, grid_id: str) -> Path:
    return Path(data_dir) / "grids" / grid_id


def run_dir(data_dir, run_id: str) -> Path:
    return Path(data_dir) / "runs" / run_id
