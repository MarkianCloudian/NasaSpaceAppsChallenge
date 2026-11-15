"""Mineral crosswalk helpers over `config/mineral_classes.json` (research D-010).

Shared by the Earth side (EMIT L2B names -> species -> class) and the Mars side
(CRISM summary parameters -> class). "Class" = subgroup id.
"""
import re


class Crosswalk:
    PREFIX = re.compile(r"^(fe2\+fe3\+|fe3\+fe2\+|fe3\+mn|fe2\+|fe3\+|mn2\+)_?")

    def __init__(self, data: dict):
        self.data = data
        self.species_class, self.class_group = {}, {}
        for g, gv in data["groups"].items():
            for sg, species in gv["subgroups"].items():
                self.class_group[sg] = g
                for sp in species:
                    self.species_class[sp] = sg
        self.classes = list(self.class_group)
        self.aqueous_groups = set(data.get("aqueous_groups", []))
        self._rules = [(re.compile(r["pattern"]), r["species"]) for r in data.get("emit_names", [])]

    def _match(self, text):
        for pat, sp in self._rules:
            if pat.search(text):
                return True, sp
        return False, None

    def emit_species(self, name: str):
        """EMIT L2B library name -> species id or None (see `emit_matching` in the config)."""
        n = name.strip().lower()
        first = self.PREFIX.sub("", n).split("+", 1)[0]
        hit, sp = self._match(first)
        if not hit:
            hit, sp = self._match(n)
        return sp

    def emit_class(self, name: str):
        sp = self.emit_species(name)
        return self.species_class.get(sp) if sp else None

    def is_aqueous(self, cls: str) -> bool:
        return self.class_group.get(cls) in self.aqueous_groups
