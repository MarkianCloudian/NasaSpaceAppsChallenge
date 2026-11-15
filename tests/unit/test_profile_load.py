"""T024."""

from __future__ import annotations

import json

import pytest

from analogfinder.errors import ValidationError
from analogfinder.profiles.load import content_hash, load_draft, load_frozen
from tests.fixtures.profiles_inline import criterion

PURPOSES = {
    "purposes": [
        {
            "purpose_id": "rover_expedition",
            "description": "x",
            "weight_method": "roc",
            "category_ranks": {
                c: i
                for i, c in enumerate(
                    [
                        "operations",
                        "terrain",
                        "geology",
                        "atmosphere",
                        "thermal",
                        "resources",
                        "biology",
                        "subsurface",
                    ],
                    1,
                )
            },
        }
    ]
}


def draft(**over):
    d = {
        "profile_id": "mars-test",
        "version": "1.0.0",
        "body": "Mars",
        "purpose": "rover_expedition",
        "reference_site": {"name": "x", "lat": 18.44, "lon": 77.45, "radius_km": 20},
        "search_constraints": {},
        "criteria": [dict(criterion(rank_in_category=1).raw)],
    }
    d.update(over)
    return d


@pytest.fixture
def env(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "purposes.json").write_text(json.dumps(PURPOSES))
    prof = tmp_path / "profiles"
    (prof / "frozen").mkdir(parents=True)
    return cfg, prof


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_draft_ok_and_errors(env):
    cfg, prof = env
    assert load_draft(write(prof / "d.json", draft()), cfg)["profile_id"] == "mars-test"
    bad = draft(purpose="landing", body="Venus")
    with pytest.raises(ValidationError) as e:
        load_draft(write(prof / "bad.json", bad), cfg)
    msg = str(e.value)
    assert "$.body" in msg and "unknown purpose 'landing'" in msg  # all errors, not the first


def test_loading_a_draft_by_ref_is_a_clear_error(env):
    _, prof = env
    write(prof / "mars-test.json", draft())
    with pytest.raises(ValidationError, match=r"mars-test@1\.0\.0 is not frozen.*draft exists"):
        load_frozen("mars-test@1.0.0", prof)
    write(prof / "frozen" / "mars-test@1.0.0.json", draft())  # a draft copied into frozen/
    with pytest.raises(ValidationError, match="is a draft"):
        load_frozen("mars-test@1.0.0", prof)


def test_load_frozen_verifies_hash(env):
    _, prof = env
    d = draft()
    frozen = {**d, "weights": {"c": 1.0}, "weights_method": "roc×roc", "frozen_at": "2026-11-15"}
    frozen["content_hash"] = content_hash(frozen)
    path = write(prof / "frozen" / "mars-test@1.0.0.json", frozen)
    p = load_frozen("mars-test@1.0.0", prof)
    assert p.ref == "mars-test@1.0.0" and p.weights == {"c": 1.0}
    frozen["criteria"][0]["tolerance"] = {"low": 9.0, "high": 9.0}  # edit after freezing
    write(path, frozen)
    with pytest.raises(ValidationError, match="content_hash mismatch"):
        load_frozen("mars-test@1.0.0", prof)


def test_content_hash_ignores_freeze_keys_and_order():
    d = draft()
    f = {**d, "weights": {"c": 1.0}, "frozen_at": "x"}
    assert content_hash(d) == content_hash(f) == content_hash(dict(reversed(list(d.items()))))
    assert len(content_hash(d)) == 64


def test_bad_ref():
    with pytest.raises(ValidationError, match="must look like"):
        load_frozen("mars-test", "profiles")
