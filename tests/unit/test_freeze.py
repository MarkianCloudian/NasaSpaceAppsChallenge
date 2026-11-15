"""T027: freezing twice is a no-op; editing and freezing the same version exits 5."""

from __future__ import annotations

import datetime as dt
import json
import shutil

import pytest

from analogfinder import cli
from analogfinder.errors import ProfileConflictError, ValidationError
from analogfinder.profiles.freeze import freeze
from analogfinder.profiles.load import load_frozen
from tests.conftest import ROOT

FIX = ROOT / "tests" / "fixtures"
CFG = FIX / "config"


@pytest.fixture
def draft(tmp_path):
    p = tmp_path / "fixture-minimal.json"
    shutil.copy(FIX / "profiles" / "valid_minimal.json", p)
    return p


def test_freeze_writes_weights_hash_and_date(draft, tmp_path):
    prof = tmp_path / "profiles"
    path, status = freeze(draft, CFG, prof, today=dt.date(2026, 11, 15))
    assert status == "written" and path == prof / "frozen" / "fixture-minimal@1.0.0.json"
    data = json.loads(path.read_text())
    assert data["weights_method"] == "roc×roc" and data["frozen_at"] == "2026-11-15"
    assert sum(data["weights"].values()) == pytest.approx(1.0, abs=1e-9)
    assert "gravity" not in data["weights"]  # not_comparable gets no weight
    p = load_frozen("fixture-minimal@1.0.0", prof)  # hash verifies
    assert p.weights == data["weights"]


def test_freeze_twice_is_noop(draft, tmp_path):
    prof = tmp_path / "profiles"
    path, _ = freeze(draft, CFG, prof, today=dt.date(2026, 11, 15))
    before = path.read_bytes()
    _, status = freeze(draft, CFG, prof, today=dt.date(2030, 1, 1))
    assert status == "reused" and path.read_bytes() == before


def test_edit_same_version_conflicts(draft, tmp_path):
    prof = tmp_path / "profiles"
    freeze(draft, CFG, prof)
    d = json.loads(draft.read_text())
    d["criteria"][1]["tolerance"] = {"high": 9}
    draft.write_text(json.dumps(d))
    with pytest.raises(ProfileConflictError, match="new version"):
        freeze(draft, CFG, prof)
    d["version"] = "1.1.0"
    draft.write_text(json.dumps(d))
    assert freeze(draft, CFG, prof)[1] == "written"


def test_invalid_draft_is_not_frozen(tmp_path):
    bad = FIX / "profiles" / "broken_target_shape.json"
    with pytest.raises(ValidationError, match="rule 9"):
        freeze(bad, CFG, tmp_path / "profiles")
    assert not (tmp_path / "profiles" / "frozen" / "fixture-minimal@1.0.0.json").exists()


def test_cli_exit_codes(draft, tmp_path, capsys):
    base = ["--config-dir", str(CFG), "freeze", "--profiles-dir", str(tmp_path / "p")]
    assert cli.main(base + ["--profile", str(draft)]) == 0
    assert cli.main(base + ["--profile", str(draft)]) == 0
    assert "unchanged, reused" in capsys.readouterr().out
    d = json.loads(draft.read_text())
    d["criteria"][0]["veto"] = 0.5
    draft.write_text(json.dumps(d))
    assert cli.main(base + ["--profile", str(draft)]) == 5
    broken = str(FIX / "profiles" / "broken_unknown_source.json")
    fresh = ["--config-dir", str(CFG), "freeze", "--profiles-dir", str(tmp_path / "fresh")]
    assert cli.main(fresh + ["--profile", broken]) == 4
