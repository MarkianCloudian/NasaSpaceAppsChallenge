"""Shipped config files validate (partial T014: files present so far; extend as files land)."""
import json
import shutil

import pytest

from analogfinder import config
from analogfinder.errors import ConfigError
from tests.conftest import ROOT

LOADERS = {
    "settings.json": config.load_settings,
    "sources.json": config.load_sources,
    "purposes.json": config.load_purposes,
    "known_analogs.json": config.load_known_analogs,
    "layers.json": config.load_layers,
    "mineral_classes.json": config.load_mineral_classes,
}
PRESENT = [n for n in LOADERS if (ROOT / "config" / n).exists()]


@pytest.mark.parametrize("name", PRESENT)
def test_shipped_config_valid(name):
    LOADERS[name]()


def test_broken_known_analogs_reports_path(tmp_path):
    shutil.copy(ROOT / "config" / "known_analogs.json", tmp_path)
    p = tmp_path / "known_analogs.json"
    data = json.loads(p.read_text())
    del data["sites"][0]["reference"]
    data["sites"][1]["lat"] = 123
    p.write_text(json.dumps(data))
    with pytest.raises(ConfigError) as e:
        config.load_known_analogs(tmp_path)
    msg = str(e.value)
    assert "known_analogs.json: $.sites[0]" in msg and "'reference' is a required property" in msg
    assert "$.sites[1].lat" in msg
