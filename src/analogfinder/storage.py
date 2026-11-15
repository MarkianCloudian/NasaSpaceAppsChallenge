"""Content-identified, never-overwritten storage (plan A3, research D-002/D-011, task T015)."""
import contextlib
import hashlib
import json
import math
import os
import secrets
from pathlib import Path

COMPLETE = "_COMPLETE"


def _normalise(obj):
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("non-finite float in fingerprinted object")
        return {"__float__": repr(obj)}
    if isinstance(obj, dict):
        return {str(k): _normalise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalise(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    raise TypeError(f"cannot fingerprint {type(obj).__name__}")


def canonical_json(obj) -> str:
    """Sorted keys, compact separators, floats via repr (exact round trip)."""
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
    (final / COMPLETE).write_text(json.dumps(manifest or {}, sort_keys=True, indent=1), encoding="utf-8")


def cache_dir(data_dir, source_id: str, dataset_version: str, request: dict) -> Path:
    """`data/cache/<source_id>/<dataset_version>/<fingerprint(request)>/` (not created)."""
    return Path(data_dir) / "cache" / source_id / dataset_version / fingerprint(request)


def write_request(directory, request: dict) -> None:
    (Path(directory) / "request.json").write_text(canonical_json(request), encoding="utf-8")


def grid_dir(data_dir, grid_id: str) -> Path:
    return Path(data_dir) / "grids" / grid_id


def run_dir(data_dir, run_id: str) -> Path:
    return Path(data_dir) / "runs" / run_id
