"""Named comparisons: the same model with one coupling switched off, or a finer mesh.

Every comparison keeps the process, the mesh (unless the comparison is the mesh) and all
other values, so differences come from the switched term alone. 'same_settings' must give
exactly zero difference; it tests the comparison itself.
"""
from __future__ import annotations

import copy

from .schema import Model

COMPARISONS = {
    "same_settings": {
        "processes": ("H", "T", "TH", "HC", "HM", "TM", "THM"),
        "changes": "nothing (an identical copy; the difference must be zero)"},
    "no_solid_thermal_expansion": {
        "processes": ("TM", "THM"),
        "changes": "thermal_expansion of every material set to 0 (no thermal stress from the solid)"},
    "no_water_thermal_expansion": {
        "processes": ("THM",),
        "changes": "water thermal_expansion set to 0 (no thermal pressurisation)"},
    "no_hydro_mechanical_coupling": {
        "processes": ("HM", "THM"),
        "changes": "biot_coefficient of every material set to 0 (pore pressure and deformation decoupled)"},
    "no_sorption": {
        "processes": ("HC",),
        "changes": "retardation set to 1 (no sorption)"},
    "no_decay": {
        "processes": ("HC",),
        "changes": "decay switched off"},
    "half_element_size": {
        "processes": ("H", "T", "TH", "HC", "HM", "TM", "THM"),
        "changes": "element size, refinement sizes halved and divisions doubled (mesh convergence check)"},
}


def variant(model: Model, kind: str) -> Model:
    if kind not in COMPARISONS:
        raise KeyError(f"unknown comparison '{kind}' (choose from: {', '.join(COMPARISONS)})")
    if model.physics.process not in COMPARISONS[kind]["processes"]:
        ok = [k for k, v in COMPARISONS.items() if model.physics.process in v["processes"]]
        raise ValueError(f"'{kind}' does not apply to process {model.physics.process} (use one of: {', '.join(ok)})")
    d = copy.deepcopy(model.model_dump(mode="json", exclude_none=True))
    if kind == "no_solid_thermal_expansion":
        for m in d["materials"].values():
            m["thermal_expansion"] = 0.0
    elif kind == "no_water_thermal_expansion":
        d["physics"].setdefault("fluid", {})["thermal_expansion"] = 0.0
    elif kind == "no_hydro_mechanical_coupling":
        for m in d["materials"].values():
            m["biot_coefficient"] = 0.0
    elif kind == "no_sorption":
        d["physics"]["components"][0]["retardation"] = 1.0
    elif kind == "no_decay":
        c = d["physics"]["components"][0]
        c.pop("half_life", None)
        c["decay_rate"] = 0.0
    elif kind == "half_element_size":
        ms = d.setdefault("mesh", {})
        if ms.get("size"):
            ms["size"] = ms["size"] / 2
        else:
            from .mesh.structured import default_size
            ms["size"] = default_size(model) / 2
        ms["divisions"] = {k: 2 * v for k, v in ms.get("divisions", {}).items()}
        for r in ms.get("refinements", []):
            r["size"] = r["size"] / 2
    d["name"] = f"{model.name}_{kind}"[:32]
    return Model.model_validate(d)


def changes_mesh(kind: str) -> bool:
    return kind == "half_element_size"
