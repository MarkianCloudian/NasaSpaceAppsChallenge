"""Load draft and frozen reference profiles (plan B1/B2, task T024).

- `load_draft(path)`: structural validation against `schemas/profile.schema.json` and a check
  that `purpose` exists in `config/purposes.json`; all problems are reported together.
- `load_frozen(ref, profiles_dir)`: reads `<profiles_dir>/frozen/<id>@<version>.json`, refuses
  drafts and verifies `content_hash`, returning a `Profile`.

`content_hash(profile)` = sha256 hex of the canonical JSON of the draft, i.e. the profile
without the keys `freeze` adds (`weights`, `weights_method`, `content_hash`, `frozen_at`).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..config import load_purposes, validate_against
from ..errors import ValidationError
from ..storage import canonical_json
from ..types import Profile

FROZEN_KEYS = ("weights", "weights_method", "content_hash", "frozen_at")
REF_RE = re.compile(r"^(?P<id>[a-z0-9][a-z0-9_-]*)@(?P<version>\d+\.\d+\.\d+)$")


def draft_part(profile: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in profile.items() if k not in FROZEN_KEYS}


def content_hash(profile: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(draft_part(profile)).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationError(f"{path}: file not found") from None
    except json.JSONDecodeError as e:
        raise ValidationError(f"{path.name}: invalid JSON at line {e.lineno}: {e.msg}") from e


def load_draft(path, config_dir=None) -> dict[str, Any]:
    """Draft profile dict; raises ValidationError listing every structural problem."""
    path = Path(path)
    draft = _read(path)
    errs = validate_against(draft, "profile.schema.json", path.name)
    purpose = draft.get("purpose")
    ids = [p["purpose_id"] for p in load_purposes(config_dir)["purposes"]]
    if purpose is not None and purpose not in ids:
        errs.append(f"{path.name}: $.purpose: unknown purpose {purpose!r} (known: {ids})")
    if errs:
        raise ValidationError(f"{len(errs)} error(s) in {path.name}:\n  " + "\n  ".join(errs))
    return draft


def frozen_path(ref: str, profiles_dir) -> Path:
    if not REF_RE.match(ref):
        raise ValidationError(f"profile reference {ref!r} must look like <profile_id>@<x.y.z>")
    return Path(profiles_dir) / "frozen" / f"{ref}.json"


def load_frozen(ref: str, profiles_dir="profiles") -> Profile:
    """Frozen profile by `id@version`; refuses drafts and tampered files."""
    path = frozen_path(ref, profiles_dir)
    if not path.exists():
        m = REF_RE.match(ref)
        drafts = [
            p.name for p in Path(profiles_dir).glob("*.json") if _profile_id(p) == m.group("id")
        ]
        hint = (
            f" A draft exists ({', '.join(drafts)}); run `analog freeze --profile ...`."
            if drafts
            else ""
        )
        raise ValidationError(f"{ref} is not frozen: {path} not found.{hint}")
    data = _read(path)
    if "content_hash" not in data or "weights" not in data:
        raise ValidationError(
            f"{path.name} is a draft, not a frozen profile (no weights/content_hash)"
        )
    if f"{data.get('profile_id')}@{data.get('version')}" != ref:
        raise ValidationError(
            f"{path.name} contains {data.get('profile_id')}@{data.get('version')}"
        )
    actual = content_hash(data)
    if actual != data["content_hash"]:
        raise ValidationError(
            f"{path.name}: content_hash mismatch (stored {data['content_hash'][:12]}…, "
            f"actual {actual[:12]}…): the frozen profile was edited; freeze a new version"
        )
    return Profile.from_frozen_json(data)


def _profile_id(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("profile_id")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
