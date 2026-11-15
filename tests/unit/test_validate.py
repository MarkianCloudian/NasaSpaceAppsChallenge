"""T070: every broken fixture fails with its rule and field path; US3 scenarios 1–4 and 1a."""

from __future__ import annotations

import json

import pytest

from analogfinder import cli
from analogfinder.profiles.load import content_hash
from analogfinder.profiles.validate import load_validation_config, summary, validate
from analogfinder.profiles.weights import compute, roc
from tests.conftest import ROOT

FIX = ROOT / "tests" / "fixtures"
CONFIG = load_validation_config(FIX / "config", FIX / "profiles")


def load(name):
    return json.loads((FIX / "profiles" / f"{name}.json").read_text(encoding="utf-8"))


def rules(errs):
    return {e.split(":")[0] for e in errs}


# fixture -> (expected rule, field path); schema-enforced duplicates may add "rule 1"
EXPECTED = {
    "broken_weights_sum": ("rule 3", "$.criteria[*].weight"),
    "broken_override_no_reason": ("rule 4", "$.category_overrides.terrain"),
    "broken_absolute_impossible": ("rule 5", "$.criteria[5].comparison"),
    "broken_missing_baseline": ("rule 6", "$.criteria[2].baseline_m"),
    "broken_baseline_mismatch": ("rule 6", "$.criteria[1].baseline_m"),
    "broken_class_overlap_no_map": ("rule 7", "$.criteria[3].class_map"),
    "broken_unknown_source": ("rule 8", "$.criteria[1].sources.earth[0]"),
    "broken_target_shape": ("rule 9", "$.criteria[0].target"),
}
SCHEMA_DUPLICATED = {"broken_override_no_reason", "broken_class_overlap_no_map"}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_broken_fixture_fails_with_rule_and_path(name):
    rule, path = EXPECTED[name]
    errs = validate(load(name), CONFIG)
    assert any(e.startswith(f"{rule}: {path}") for e in errs), errs
    allowed = {rule, "rule 1"} if name in SCHEMA_DUPLICATED else {rule}
    assert rules(errs) <= allowed, errs  # each fixture targets exactly one rule


def test_valid_minimal_passes_with_counts():
    d = load("valid_minimal")
    assert validate(d, CONFIG) == []
    assert summary(d) == {
        "profile_id": "fixture-minimal",
        "version": "1.0.0",
        "scored": 5,
        "veto": 2,
        "normalized": 1,
        "not_comparable": 1,
    }


def test_us3_1_weights_sum_names_profile_and_total():
    errs = validate(load("broken_weights_sum"), CONFIG)
    assert any("fixture-minimal@1.0.0" in e and "0.900000" in e for e in errs)


def test_us3_1a_weights_are_roc_times_roc_and_sum_to_one():
    d = load("valid_minimal")
    w, method = compute(d, CONFIG["purposes"])
    assert method == "roc×roc" and sum(w.values()) == pytest.approx(1.0, abs=1e-9)
    # categories present: operations(1) terrain(2) geology(3) atmosphere(4) resources(6);
    # ROC over all 8 ranks, absent categories dropped and renormalised; one criterion each,
    # except operations has 1 scored criterion (gravity is not_comparable) → within weight 1
    r8 = roc(8)
    present = {
        "operations": r8[0],
        "terrain": r8[1],
        "geology": r8[2],
        "atmosphere": r8[3],
        "resources": r8[5],
    }
    tot = sum(present.values())
    expect = {
        "traverse_slope": present["operations"] / tot,
        "regional_slope": present["terrain"] / tot,
        "mineral_classes": present["geology"] / tot,
        "hyperarid": present["atmosphere"] / tot,
        "aqueous_minerals": present["resources"] / tot,
    }
    assert w == pytest.approx(expect, abs=2e-6)


def test_us3_2_absolute_impossible_asks_for_normalized_or_not_comparable():
    errs = validate(load("broken_absolute_impossible"), CONFIG)
    assert any("'normalized' or 'not_comparable'" in e for e in errs)


def test_us3_3_override_without_reason_names_category():
    errs = validate(load("broken_override_no_reason"), CONFIG)
    assert any(e.startswith("rule 4") and "'terrain'" in e for e in errs)


def test_rule_10_frozen_version_with_other_hash(tmp_path):
    d = load("valid_minimal")
    (tmp_path / "frozen").mkdir()
    frozen = dict(d, content_hash=content_hash(d))
    (tmp_path / "frozen" / "fixture-minimal@1.0.0.json").write_text(json.dumps(frozen))
    cfg = dict(CONFIG, profiles_dir=tmp_path)
    assert validate(d, cfg) == []  # same content: fine
    d["criteria"][0]["tolerance"] = {"percentile": 0.2}
    assert any(e.startswith("rule 10: $.version") for e in validate(d, cfg))


def test_all_errors_collected():
    d = load("valid_minimal")
    d["criteria"][1]["baseline_m"] = 30  # rule 6
    d["criteria"][0]["sources"]["earth"] = ["nope"]  # rule 8
    assert {"rule 6", "rule 8"} <= rules(validate(d, CONFIG))


def test_cli_us3_4_reports_counts_and_exit_codes(capsys):
    base = ["--config-dir", str(FIX / "config"), "validate"]
    ok = cli.main(base + ["--profile", str(FIX / "profiles" / "valid_minimal.json")])
    out = capsys.readouterr().out
    assert ok == 0
    assert "fixture-minimal@1.0.0: OK — scored 5, veto 2, normalized 1, not comparable 1" in out
    bad = cli.main(base + ["--profile", str(FIX / "profiles" / "broken_target_shape.json")])
    assert bad == 4 and "rule 9" in capsys.readouterr().err
