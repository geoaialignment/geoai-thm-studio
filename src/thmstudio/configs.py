"""Supported configurations: the only combinations the harness will compute.

Each configuration names its process, shapes, conditions and the verification
cases that back it. Anything else is refused with a pointer to the company.
"""
from __future__ import annotations

from dataclasses import dataclass

CONTACT = ("This is outside what the free version verifies. GeoAI Alignment, Inc. offers this as a "
           "commercial service (site models, large 3D, other physics): https://geoaialign.ai")


@dataclass(frozen=True)
class Configuration:
    id: str
    process: str
    shapes: tuple[str, ...]
    title: str
    cases: tuple[str, ...]
    steady: bool = True
    transient: bool = True
    variables: tuple[str, ...] = ()
    source: str | None = None       # axisym_source only: 'point' or 'canister'
    demonstration: bool = False     # checked by consistency tests, not by an exact solution
    buoyant: bool = False           # HC with concentration-dependent density


CONFIGURATIONS = (
    Configuration("H-2D", "H", ("rect", "strip"), "groundwater flow in a 2D section or plan",
                  ("V1a",), variables=("head", "pressure")),
    Configuration("H-AX-well", "H", ("axisym_well",), "radial flow to a well (axisymmetric)",
                  ("V1b",), variables=("head", "pressure")),
    Configuration("H-3D", "H", ("box",), "groundwater flow in a 3D box", ("V1c", "V1c-flow"),
                  variables=("head", "pressure")),
    Configuration("T-2D", "T", ("rect", "rect_inclusion", "strip"), "heat conduction in 2D",
                  ("V2a", "V2a-tri", "V2b", "V2b-power", "V2d"), variables=("temperature",)),
    Configuration("T-3D", "T", ("box",), "heat conduction in a 3D box", ("V2c", "V2c-steady"),
                  variables=("temperature",)),
    Configuration("TH-2D", "TH", ("rect", "strip"), "heat transport by groundwater flow in 2D",
                  ("V3", "V3-water"), steady=False, variables=("temperature", "head", "pressure")),
    Configuration("HC-2D", "HC", ("rect", "strip"), "solute transport (advection, dispersion, sorption, decay) in 2D",
                  ("V6a", "V6b"), steady=False, variables=("head", "pressure", "concentration")),
    Configuration("HC-2D-density", "HC", ("rect",), "density-driven (buoyant) solute transport in a vertical "
                  "section", ("E2",), steady=False, variables=("head", "pressure", "concentration"), buoyant=True),
    Configuration("HM-2D", "HM", ("rect",), "consolidation of saturated ground under load (plane strain; "
                  "verified with a 1D column)", ("V4", "V4b"), steady=False, variables=("head", "pressure", "displacement")),
    Configuration("TM-2D", "TM", ("rect",), "thermal expansion and thermal stress in rock (plane strain)",
                  ("V7a", "V7b", "V7c"), variables=("temperature", "displacement")),
    Configuration("THM-AX", "THM", ("axisym_source",), "point heat source in saturated rock (axisymmetric)",
                  ("V5",), steady=False, variables=("temperature", "head", "pressure", "displacement"), source="point"),
    Configuration("THM-AX-repository", "THM", ("axisym_source",), "heated canister in a buffer-filled hole in rock "
                  "(axisymmetric; demonstration)", ("E1", "E1a"), steady=False,
                  variables=("temperature", "head", "pressure", "displacement"), source="canister", demonstration=True),
)

BY_ID = {c.id: c for c in CONFIGURATIONS}


def find(process: str, shape: str, source: str | None = None, buoyant: bool = False) -> Configuration | None:
    for c in CONFIGURATIONS:
        if (c.process == process and shape in c.shapes and (c.source is None or c.source == source)
                and c.buoyant == buoyant):
            return c
    return None


def supported_shapes(process: str) -> list[str]:
    return sorted({s for c in CONFIGURATIONS if c.process == process for s in c.shapes})
