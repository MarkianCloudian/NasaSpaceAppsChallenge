"""Freeze a draft profile into an immutable, versioned file (plan B2, task T027, FR-009).

`freeze(draft_path, config_dir, profiles_dir)`:
  1. load the draft (schema + purpose check, T024);
  2. if `profiles/frozen/<id>@<version>.json` exists: same content hash -> "unchanged, reused";
     different hash -> ProfileConflictError (exit 5): change the version instead;
  3. validate (rules 1-9, T068) -> ValidationError (exit 4) listing every problem;
  4. compute weights (T025) and write the draft plus `weights`, `weights_method`,
     `content_hash` (sha256 of the canonical JSON of the draft) and `frozen_at` (ISO date),
     via a temporary file renamed into place, so a frozen file is never partially written.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from ..errors import ProfileConflictError, ValidationError
from .load import content_hash, frozen_path, load_draft
from .validate import load_validation_config, validate
from .weights import compute


def freeze(draft_path, config_dir=None, profiles_dir="profiles", today: dt.date | None = None):
    """Return (frozen file path, "written" | "reused")."""
    draft = load_draft(draft_path, config_dir)
    ref = f"{draft['profile_id']}@{draft['version']}"
    target = frozen_path(ref, profiles_dir)
    digest = content_hash(draft)
    if target.exists():
        stored = json.loads(target.read_text(encoding="utf-8")).get("content_hash")
        if stored == digest:
            return target, "reused"
        raise ProfileConflictError(
            f"{ref} is already frozen with different content (stored {str(stored)[:12]}…, "
            f"draft {digest[:12]}…); give the edited profile a new version"
        )
    cfg = load_validation_config(config_dir, None)  # rule 10 handled above
    errs = validate(draft, cfg)
    if errs:
        raise ValidationError(f"{len(errs)} error(s) in {ref}:\n  " + "\n  ".join(errs))
    weights, method = compute(draft, cfg["purposes"])
    frozen = {
        **draft,
        "weights": weights,
        "weights_method": method,
        "content_hash": digest,
        "frozen_at": (today or dt.date.today()).isoformat(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.partial-{os.getpid()}")
    tmp.write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return Path(target), "written"
