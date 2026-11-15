"""T057 online smoke test (skipped by default; run `uv run pytest -m online`).

Needs network, NASA Earthdata login (`~/.netrc`) and Copernicus (`~/.cdsapirc`). It uses a
temporary config dir and data dir; nothing is written into the repository.

Window: the settings contract (`settings.schema.json`) only has `grid.lat_range`, no longitude
range, so the temporary override restricts latitude to the Atacama band (-30…-20). Add a
`grid.lon_range` (-72…-66) here once the contract provides one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.online

PROFILE_DRAFT = "mars-rover-jezero.json"
LAT_RANGE = [-30, -20]


def analog(root: Path, work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-c",
        "import sys; from analogfinder.cli import main; sys.exit(main())",
        "--config-dir",
        str(work / "config"),
        "--data-dir",
        str(work / "data"),
        *args,
    ]
    return subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=3600)


@pytest.fixture(scope="module")
def workspace(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("smoke")
    shutil.copytree(repo_root / "config", work / "config")
    shutil.copytree(repo_root / "profiles", work / "profiles")
    settings_path = work / "config" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["grid"]["lat_range"] = LAT_RANGE
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return work


def _frozen_ref(work: Path) -> str:
    draft = json.loads((work / "profiles" / PROFILE_DRAFT).read_text(encoding="utf-8"))
    return f"{draft['profile_id']}@{draft['version']}"


def _results_of(work: Path, proc: subprocess.CompletedProcess[str]) -> dict:
    """Load results.json of the run id printed as `run: <id>` or `reused <id>`."""
    for line in (proc.stdout + proc.stderr).splitlines():
        line = line.strip()
        if line.startswith(("run:", "reused ")):
            run_id = line.split()[-1]
            path = work / "data" / "runs" / run_id / "results.json"
            return json.loads(path.read_text(encoding="utf-8"))
    pytest.fail(f"no run id in output:\n{proc.stdout}\n{proc.stderr}")


def test_online_smoke(repo_root: Path, workspace: Path):
    ref = _frozen_ref(workspace)

    frozen = analog(
        repo_root, workspace, "freeze", "--profile", str(workspace / "profiles" / PROFILE_DRAFT)
    )
    assert frozen.returncode == 0, frozen.stderr

    chk = analog(repo_root, workspace, "check", "--profile", ref)
    assert chk.returncode == 0, f"source check failed (Earthdata login?): {chk.stderr}"

    grid = analog(repo_root, workspace, "grid")
    assert grid.returncode in (0, 6), grid.stderr  # 6 = partial (some layers missing)

    # (a) screening preview: nothing ranked, screened areas carry an upper bound
    prev = analog(repo_root, workspace, "run", "--profile", ref, "--skip-refine")
    assert prev.returncode in (0, 6), prev.stderr
    results = _results_of(workspace, prev)
    assert results["run_record"]["refinement"]["stop"] == "skipped"
    screened = [a for a in results["candidates"] if a.get("status") == "screened_only"]
    assert screened, "no screened_only area in the Atacama window"
    assert all("upper_bound" in a for a in screened)

    # (b) refinement with small caps
    full = analog(
        repo_root,
        workspace,
        "run",
        "--profile",
        ref,
        "--max-terrain-areas",
        "5",
        "--max-mineral-areas",
        "2",
    )
    assert full.returncode in (0, 6, 7), full.stderr
    results = _results_of(workspace, full)
    ranked = [a for a in results["candidates"] if a.get("status") == "ranked"]
    if not ranked:
        insufficient = [a for a in results["candidates"] if a.get("status") == "insufficient_data"]
        assert insufficient, "neither ranked nor insufficient_data areas"
        assert full.stderr.strip(), "insufficient_data without a logged reason"
