"""Mineral crosswalk helpers over `config/mineral_classes.json` (research D-010).

Shared by the Earth side (EMIT L2B names -> species -> class) and the Mars side
(CRISM summary parameters -> class). "Class" = subgroup id.
"""

from __future__ import annotations

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

    # --- hierarchy credit for class_overlap scoring (research D-010) -----------------------

    def lineage(self, node: str):
        """(group, subgroup, species) of a node id; missing levels are None."""
        if node in self.species_class:
            sg = self.species_class[node]
            return self.class_group[sg], sg, node
        if node in self.class_group:
            return self.class_group[node], node, None
        if node in self.class_group.values():
            return node, None, None
        raise KeyError(f"unknown mineral node {node!r}")

    def credit(self, target: str, earth: str) -> float:
        """Hierarchy credit between two nodes (species, subgroup or group ids).

        1.0 (same_species) when the nodes are equal or one contains the other (e.g. target
        subgroup fe_mg_smectite vs Earth species saponite: the Earth item IS that class);
        0.7 (same_subgroup) for different species of one subgroup; 0.4 (same_group) for
        different subgroups of one group; 0 otherwise.
        """
        pc = self.data["partial_credit"]
        tg, ts, tsp = self.lineage(target)
        eg, es, esp = self.lineage(earth)
        if tg != eg:
            return pc["otherwise"]
        if ts is None or es is None:  # one side is a whole group containing the other
            return pc["same_species"]
        if ts != es:
            return pc["same_group"]
        if tsp is None or esp is None or tsp == esp:
            return pc["same_species"]
        return pc["same_subgroup"]
