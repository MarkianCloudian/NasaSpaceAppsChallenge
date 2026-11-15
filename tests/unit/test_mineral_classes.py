"""T013: shipped mineral_classes.json loads; structural errors are reported."""

from __future__ import annotations

import json

from analogfinder import config
from tests.conftest import ROOT


def test_shipped_file_loads():
    mc = config.load_mineral_classes()
    assert set(mc["partial_credit"]) >= {"same_species", "same_subgroup", "same_group", "otherwise"}


def test_mineral_classes_structural_errors():
    data = json.loads((ROOT / "config" / "mineral_classes.json").read_text())
    data["crism_rules"].append({"class": "nope", "parameter": "BD1900_2", "threshold": "x"})
    data["emit_names"].append({"pattern": "(", "species": "unobtainium"})
    errs = config.check_mineral_classes(data)
    joined = "\n".join(errs)
    assert "unknown subgroup 'nope'" in joined
    assert "threshold: must be a number" in joined
    assert "listed in excluded_parameters" in joined
    assert "invalid regex" in joined and "unknown species 'unobtainium'" in joined
