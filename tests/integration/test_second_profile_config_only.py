"""T075: a new purpose and profile run with configuration changes only (SC-007, US3 scenario 6)."""

from __future__ import annotations

import json
import shutil

import pytest

from analogfinder import cli, pipeline
from tests.conftest import ROOT
from tests.fixtures.synthetic_run import synthetic_hooks

LANDING = {
    "purpose_id": "landing",
    "description": "Fixture purpose: safe landing (terrain and operations first)",
    "weight_method": "roc",
    "category_ranks": {
        "operations": 1,
        "terrain": 2,
        "atmosphere": 3,
        "biology": 4,
        "geology": 5,
        "thermal": 6,
        "resources": 7,
        "subsurface": 8,
    },
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    purposes = json.loads((cfg / "purposes.json").read_text())
    purposes["purposes"].append(LANDING)
    (cfg / "purposes.json").write_text(json.dumps(purposes, indent=2))
    prof = tmp_path / "profiles"
    prof.mkdir()
    shutil.copy(ROOT / "profiles" / "mars-rover-jezero.json", prof)
    shutil.copy(ROOT / "tests" / "fixtures" / "profiles" / "fixture-mars-landing.json", prof)
    monkeypatch.setattr(pipeline, "DEFAULT_HOOKS", synthetic_hooks())
    base = ["--config-dir", str(cfg), "--data-dir", str(tmp_path / "data")]
    return base, prof, tmp_path


def last_run_id(out: str) -> str:
    words = out.split()
    return words[words.index("run:") + 1]


def test_second_profile_validate_freeze_run(env, capsys):
    base, prof, tmp = env
    pdir = ["--profiles-dir", str(prof)]
    landing = str(prof / "fixture-mars-landing.json")
    assert cli.main(base + ["validate", "--profile", landing] + pdir) == 0
    assert "fixture-mars-landing@1.0.0: OK" in capsys.readouterr().out
    for f in ("fixture-mars-landing.json", "mars-rover-jezero.json"):
        assert cli.main(base + ["freeze", "--profile", str(prof / f)] + pdir) == 0
    capsys.readouterr()
    assert cli.main(base + ["run", "--profile", "fixture-mars-landing@1.0.0"] + pdir) in (0, 6, 7)
    landing_run = last_run_id(capsys.readouterr().out)
    assert cli.main(base + ["run", "--profile", "mars-rover-jezero@1.0.0"] + pdir) in (0, 6, 7)
    rover_run = last_run_id(capsys.readouterr().out)
    assert landing_run != rover_run
    runs = tmp / "data" / "runs"
    a = json.loads((runs / landing_run / "results.json").read_text())
    b = json.loads((runs / rover_run / "results.json").read_text())
    assert a["run_record"]["profile"]["id"] == "fixture-mars-landing"
    assert b["run_record"]["profile"]["id"] == "mars-rover-jezero"
    # each run lists only its own profile's criteria (separate result tables)
    ids_a = {r["criterion_id"] for c in a["candidates"] for r in c["results"]}
    ids_b = {r["criterion_id"] for c in b["candidates"] for r in c["results"]}
    assert "mineral_classes" not in ids_a and "mineral_classes" in ids_b
    index = json.loads((runs / "index.json").read_text())
    assert index["fixture-mars-landing@1.0.0"][0]["run_id"] == landing_run
    frozen = json.loads((prof / "frozen" / "fixture-mars-landing@1.0.0.json").read_text())
    assert frozen["purpose"] == "landing" and abs(sum(frozen["weights"].values()) - 1) < 1e-9
