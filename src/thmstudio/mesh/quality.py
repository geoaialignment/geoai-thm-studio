"""Mesh quality: element shape, analytic measures, boundary-bulk links, OGS checkMesh.

Every issue carries a fix the agent can apply with set_mesh.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .contract import CORNERS, HEXAHEDRON, MeshBundle

MAX_ASPECT = 20.0
MIN_ANGLE_TRI = 15.0
MIN_ANGLE_QUAD = 30.0


@dataclass
class Issue:
    level: str        # "error" blocks the model check, "warning" does not
    code: str
    message: str
    fix: str = ""

    def as_dict(self):
        return {"level": self.level, "code": self.code, "message": self.message, "fix": self.fix}


@dataclass
class QualityReport:
    stats: dict = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def as_dict(self):
        return {"ok": self.ok, "stats": self.stats, "issues": [i.as_dict() for i in self.issues]}


def _corners(bulk) -> np.ndarray:
    ct = int(bulk.celltypes[0])
    k = CORNERS[ct]
    conn = bulk.cell_connectivity.reshape(bulk.n_cells, -1)
    return bulk.points[conn[:, :k]], ct


def shape_metrics(bulk) -> dict[str, np.ndarray]:
    P, ct = _corners(bulk)
    if ct == HEXAHEDRON:
        # scaled Jacobian at the 8 corners
        nb = {0: (1, 3, 4), 1: (2, 0, 5), 2: (3, 1, 6), 3: (0, 2, 7), 4: (7, 5, 0), 5: (4, 6, 1),
              6: (5, 7, 2), 7: (6, 4, 3)}
        sj = []
        for c, (a, b, d) in nb.items():
            e1, e2, e3 = P[:, a] - P[:, c], P[:, b] - P[:, c], P[:, d] - P[:, c]
            det = np.einsum("ij,ij->i", e1, np.cross(e2, e3))
            sj.append(det / (np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(e3, axis=1)))
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        L = np.stack([np.linalg.norm(P[:, a] - P[:, b], axis=1) for a, b in edges], axis=1)
        return {"scaled_jacobian": np.min(np.stack(sj, 1), 1), "aspect": L.max(1) / L.min(1)}
    P = P[:, :, :2]
    n = P.shape[1]
    nxt = np.roll(np.arange(n), -1)
    E = P[:, nxt] - P  # edge vectors
    L = np.linalg.norm(E, axis=2)
    area = 0.5 * np.sum(P[:, :, 0] * P[:, nxt, 1] - P[:, nxt, 0] * P[:, :, 1], axis=1)
    prv = np.roll(np.arange(n), 1)
    a, b = -E[:, prv], E
    cosang = np.einsum("ijk,ijk->ij", a, b) / (np.linalg.norm(a, axis=2) * np.linalg.norm(b, axis=2))
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    return {"signed_area": area, "aspect": L.max(1) / L.min(1), "min_angle": ang.min(1), "max_angle": ang.max(1)}


def _measure(mesh) -> np.ndarray:
    s = mesh.compute_cell_sizes(length=True, area=True, volume=True)
    for key in ("Volume", "Area", "Length"):
        v = np.abs(np.asarray(s.cell_data[key]))
        if v.sum() > 0:
            return v
    return np.zeros(mesh.n_cells)


def check_links(bundle: MeshBundle) -> list[str]:
    """Every boundary cell must lie on the bulk element it names."""
    conn = bundle.bulk.cell_connectivity.reshape(bundle.bulk.n_cells, -1)
    bad = []
    for name, m in {**bundle.boundaries, **bundle.interfaces}.items():
        bn = np.asarray(m.point_data["bulk_node_ids"]).astype(np.int64)
        be = np.asarray(m.cell_data["bulk_element_ids"]).astype(np.int64)
        lc = m.cell_connectivity.reshape(m.n_cells, -1)
        for c in range(m.n_cells):
            if not set(bn[lc[c]]) <= set(conn[be[c]]):
                bad.append(name)
                break
        if not np.allclose(m.points, bundle.bulk.points[bn]):
            bad.append(name)
    return sorted(set(bad))


def ogs_checkmesh(vtu: Path) -> dict:
    """Run OGS checkMesh -v. Clean means no geometry errors and no holes."""
    exe = Path(sys.executable).parent / "checkMesh"
    p = subprocess.run([str(exe), "-v", str(vtu)], capture_output=True, text=True, timeout=120)
    text = p.stdout + p.stderr
    qc = text.split("Mesh Quality Control:")[-1]
    findings = [l.split("info:")[-1].strip() for l in qc.splitlines()
                if l.strip() and not re.search(r"No (errors|elements|holes) found|Looking for|Testing|property vectors|"
                                                r"Remark|Found 0 ", l)]
    clean = (p.returncode == 0 and "No errors found." in text and "No holes found" in text and not findings)
    return {"returncode": p.returncode, "clean": clean, "findings": findings[:10]}


def _rel_tol(bundle: MeshBundle) -> float:
    """Allowed relative error of measures: exact for straight edges, polygon error for circles."""
    if "inclusion_boundary" not in bundle.interfaces:
        return 1e-9
    n = bundle.interfaces["inclusion_boundary"].n_cells
    return 1e-9 if bundle.order == 2 and n >= 16 else max(1e-9, (2 * math.pi / n) ** 2 / 4)


def check(bundle: MeshBundle, max_elements: int, vtu: Path | None = None) -> QualityReport:
    rep = QualityReport()
    met = shape_metrics(bundle.bulk)
    st = {"elements": int(bundle.bulk.n_cells), "nodes": int(bundle.bulk.n_points),
          "element_type": bundle.cell_type, "max_aspect": float(met["aspect"].max())}
    h = np.sqrt(_measure(bundle.bulk)) if bundle.dim == 2 else np.cbrt(_measure(bundle.bulk))
    st["element_size_min"], st["element_size_max"] = float(h.min()), float(h.max())
    if "min_angle" in met:
        st["min_angle_deg"] = float(met["min_angle"].min())
        if (met["signed_area"] <= 0).any():
            rep.issues.append(Issue("error", "inverted_elements",
                                    f"{int((met['signed_area'] <= 0).sum())} elements have zero or negative area",
                                    "report this mesh; it is a harness defect"))
        tri = bundle.cell_type.startswith("Tri")
        lim = MIN_ANGLE_TRI if tri else MIN_ANGLE_QUAD
        nbad = int((met["min_angle"] < lim).sum())
        if nbad:
            rep.issues.append(Issue("warning", "small_angles", f"{nbad} elements have an angle below {lim:.0f} deg",
                                    "use a smaller size or a smaller growth near curved boundaries"))
    else:
        st["min_scaled_jacobian"] = float(met["scaled_jacobian"].min())
        if (met["scaled_jacobian"] <= 0).any():
            rep.issues.append(Issue("error", "inverted_elements", "some hexahedra have a non-positive Jacobian",
                                    "report this mesh; it is a harness defect"))
    nasp = int((met["aspect"] > MAX_ASPECT).sum())
    if nasp:
        rep.issues.append(Issue("warning", "high_aspect_ratio",
                                f"{nasp} elements are stretched more than {MAX_ASPECT:.0f}:1 "
                                f"(largest {met['aspect'].max():.0f}:1)",
                                "add divisions along the long side, or reduce the growth of refinements"))
    if bundle.bulk.n_cells > max_elements:
        rep.issues.append(Issue("error", "too_many_elements",
                                f"{bundle.bulk.n_cells} elements exceed the limit of {max_elements} for this configuration",
                                "use a larger size or fewer refinements; larger models are a commercial service "
                                "(contact GeoAI Alignment)"))
    # analytic measures
    tol = _rel_tol(bundle)
    cell_meas = _measure(bundle.bulk)
    mats = np.asarray(bundle.bulk.cell_data["MaterialIDs"])
    meas = {}
    for name, rid in bundle.regions.items():
        got = float(cell_meas[mats == rid].sum())
        exp = bundle.expected["regions"][name]
        meas[f"region:{name}"] = (got, exp)
        if abs(got - exp) > tol * max(abs(exp), 1e-300):
            rep.issues.append(Issue("error", "region_measure",
                                    f"region '{name}' measures {got:.6g}, expected {exp:.6g}",
                                    "report this mesh; a region may be missing or overlapping"))
    for name, exp in bundle.expected["boundaries"].items():
        m = bundle.boundaries.get(name) or bundle.interfaces.get(name)
        if m is None:
            rep.issues.append(Issue("error", "missing_boundary", f"boundary '{name}' was not built",
                                    "report this mesh; it is a harness defect"))
            continue
        got = float(_measure(m).sum())
        meas[f"boundary:{name}"] = (got, exp)
        if abs(got - exp) > tol * max(abs(exp), 1e-300):
            rep.issues.append(Issue("error", "boundary_measure",
                                    f"boundary '{name}' measures {got:.6g}, expected {exp:.6g}",
                                    "report this mesh; it is a harness defect"))
    st["measures"] = {k: {"mesh": round(g, 10), "expected": round(e, 10)} for k, (g, e) in meas.items()}
    st["measure_tolerance"] = tol
    bad = check_links(bundle)
    if bad:
        rep.issues.append(Issue("error", "boundary_links", f"boundaries not attached to the bulk mesh: {bad}",
                                "report this mesh; it is a harness defect"))
    if bundle.axisymmetric and bundle.bulk.points[:, 0].min() < -1e-12:
        rep.issues.append(Issue("error", "negative_radius", "axisymmetric mesh has nodes at r < 0",
                                "report this mesh; it is a harness defect"))
    if vtu is not None:
        cm = ogs_checkmesh(vtu)
        st["ogs_checkMesh"] = cm
        if not cm["clean"]:
            rep.issues.append(Issue("error", "ogs_checkmesh", "OGS checkMesh reported defects: "
                                    + "; ".join(cm["findings"]), "report this mesh; it is a harness defect"))
    rep.stats = st
    return rep
