"""Mesh stage: settings -> engine -> bundle -> quality report -> preview."""
from __future__ import annotations

from pathlib import Path

from ..schema import Model
from . import gmsh_engine, structured
from .contract import MeshBundle
from .quality import QualityReport, check
from .structured import MeshError

ORDER = {"H": 1, "T": 1, "TH": 1, "HC": 1, "HM": 2, "TM": 2, "THM": 2}
MAX_ELEMENTS = {2: 60_000, 3: 120_000}
MAX_ELEMENTS_MECHANICS = 15_000  # quadratic coupled models; larger ones run too long for an interactive tool
# Meshes up to this multiple of the limit are built and reported by the quality check with their exact count;
# requests estimated above it are refused before anything is allocated.
REFUSE_FACTOR = 10


def element_order(model: Model) -> int:
    return ORDER[model.physics.process]


def choose(model: Model) -> tuple[str, str]:
    """(engine, element) for the model's shape and element setting."""
    kind, el = model.geometry.kind, model.mesh.element
    if kind == "box":
        if el not in ("auto", "hex"):
            raise MeshError("3D boxes use hexahedra in v0.1 (tetrahedra come in v0.2)")
        return "structured", "hex"
    if el == "hex":
        raise MeshError("hexahedra are for 3D boxes; use quad or tri in 2D")
    if kind == "rect_inclusion":
        return "gmsh", "tri" if el == "auto" else el
    if kind == "axisym_source":
        if el not in ("auto", "quad"):
            raise MeshError("the axisymmetric source shape is meshed with quadrilaterals")
        return "structured", "quad"
    if el in ("auto", "quad"):
        return "structured", "quad"
    return "gmsh", "tri"


def build_mesh(model: Model, workdir: Path, write: bool = True) -> tuple[MeshBundle, QualityReport]:
    engine, element = choose(model)
    order = element_order(model)
    cap = MAX_ELEMENTS_MECHANICS if order == 2 else MAX_ELEMENTS[3 if model.geometry.kind == "box" else 2]
    if engine == "structured":
        bundle = structured.build(model, order, REFUSE_FACTOR * cap)
    else:
        bundle = gmsh_engine.build(model, workdir / "gmsh", order, element, REFUSE_FACTOR * cap)
    vtu = None
    if write:
        files = bundle.write(workdir)
        vtu = workdir / files["bulk"]
    report = check(bundle, cap, vtu)
    if write:
        report.stats["file_hash"] = bundle.file_hash(workdir)
    return bundle, report


__all__ = ["MeshBundle", "MeshError", "QualityReport", "build_mesh", "choose", "element_order"]
