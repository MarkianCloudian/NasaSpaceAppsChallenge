"""T071: a frozen profile version cannot change under a recorded run (US3 scenario 5, FR-009)."""

from __future__ import annotations

import json
import shutil

import pytest

from analogfinder import cli, errors, pipeline
from tests.conftest import ROOT
from tests.fixtures.synthetic_run import synthetic_hooks


@pytest.fixture
def env(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    prof.mkdir()
    draft = prof / "mars-rover-jezero.json"
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", draft)
    monkeypatch.setattr(pipeline, "DEFAULT_HOOKS", synthetic_hooks())
    base = ["--config-dir", str(ROOT / "config"), "--data-dir", str(tmp_path / "data")]
    return draft, prof, base


def edit(path, fn):
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d, indent=2))


def run_id(capsys):
    out = capsys.readouterr().out.split()
    return out[out.index("run:") + 1] if "run:" in out else out[out.index("reused") + 1]


def test_freeze_run_edit_bump(env, capsys):
    draft, prof, base = env
    pdir = ["--profiles-dir", str(prof)]
    # freeze -> run
    assert cli.main(base + ["freeze", "--profile", str(draft)] + pdir) == 0
    assert cli.main(base + ["run", "--profile", "mars-rover-jezero@1.0.0"] + pdir) == 0
    first = run_id(capsys)
    # edit a tolerance, freeze the same version -> exit 5, frozen file untouched
    frozen = prof / "frozen" / "mars-rover-jezero@1.0.0.json"
    before = frozen.read_bytes()
    edit(draft, lambda d: d["criteria"][6]["tolerance"].update(high=12))
    assert cli.main(base + ["freeze", "--profile", str(draft)] + pdir) == errors.PROFILE_CONFLICT
    assert frozen.read_bytes() == before
    # editing the frozen file itself (bypassing freeze) -> run refuses
    edit(frozen, lambda d: d["criteria"][6]["tolerance"].update(high=12))
    assert (
        cli.main(base + ["run", "--profile", "mars-rover-jezero@1.0.0"] + pdir)
        == errors.VALIDATION_FAILED
    )
    assert "content_hash mismatch" in capsys.readouterr().err
    frozen.write_bytes(before)
    # bump the version -> freeze and run succeed with a new run_id; the old run is untouched
    old_dir = prof.parent / "data" / "runs" / first
    old_files = sorted(p.name for p in old_dir.iterdir())
    edit(draft, lambda d: d.update(version="1.1.0"))
    assert cli.main(base + ["freeze", "--profile", str(draft)] + pdir) == 0
    assert cli.main(base + ["run", "--profile", "mars-rover-jezero@1.1.0"] + pdir) == 0
    second = run_id(capsys)
    assert second != first and sorted(p.name for p in old_dir.iterdir()) == old_files
    index = json.loads((prof.parent / "data" / "runs" / "index.json").read_text())
    assert set(index) == {"mars-rover-jezero@1.0.0", "mars-rover-jezero@1.1.0"}


def test_run_refuses_drafts(env, capsys):
    draft, prof, base = env
    code = cli.main(
        base + ["run", "--profile", "mars-rover-jezero@1.0.0", "--profiles-dir", str(prof)]
    )
    assert code == errors.VALIDATION_FAILED and "not frozen" in capsys.readouterr().err
