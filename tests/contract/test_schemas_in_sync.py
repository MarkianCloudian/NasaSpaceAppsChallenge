"""T006: runtime schema copies equal the contracts and are valid Draft 2020-12 schemas."""
import json

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import ROOT

CONTRACTS = ROOT / "specs" / "001-earth-analog-finder" / "contracts"
SCHEMAS = sorted(CONTRACTS.glob("*.schema.json"))


def test_every_contract_has_a_copy():
    assert SCHEMAS
    assert {p.name for p in SCHEMAS} == {p.name for p in (ROOT / "schemas").glob("*.schema.json")}


@pytest.mark.parametrize("contract", SCHEMAS, ids=lambda p: p.name)
def test_copy_identical_and_valid(contract):
    copy = ROOT / "schemas" / contract.name
    assert copy.read_bytes() == contract.read_bytes(), f"schemas/{contract.name} differs from its contract"
    Draft202012Validator.check_schema(json.loads(copy.read_text(encoding="utf-8")))
