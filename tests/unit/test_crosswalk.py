import json

import pytest

from analogfinder.crosswalk import Crosswalk
from tests.conftest import ROOT

X = Crosswalk(json.loads((ROOT / "config" / "mineral_classes.json").read_text()))


@pytest.mark.parametrize(
    "name,cls",
    [
        ("sulfate_gypsum", "sulfate"),
        ("fe3+_sulfate_kjarosite200", "sulfate"),
        ("sulfate+kaolingrp_natroalun+dickite", "sulfate"),
        ("fe3+_goeth+jarosite", "fe_oxide"),  # first component of a mixture wins
        ("fe3+_hematite.1+goethite.9hg1", "fe_oxide"),
        ("fe3+_smectite_nontronite", "fe_mg_smectite"),
        ("smectite_montmorillonite_na_highswelling", "fe_mg_smectite"),
        ("kaolin.3+smect.7", "al_oh_clay"),
        ("micagrp_illite", "al_oh_clay"),
        ("carbonate_dolo+.5ca-mont", "carbonate"),
        ("carbonate_magnesite", "carbonate"),
        ("fe2+_olivine-fine-gr", "olivine"),
        ("fe2+_pyroxene.hypersthene", "pyroxene"),
        ("organic_benzene+montswy", None),
        ("chlorite", None),  # not in the v1 hierarchy
    ],
)
def test_emit_class(name, cls):
    assert X.emit_class(name) == cls


def test_aqueous():
    assert (
        X.is_aqueous("sulfate") and X.is_aqueous("fe_mg_smectite") and not X.is_aqueous("olivine")
    )
