"""gmsh engine for G2 (circular inclusion) and triangle meshes of the rectangular shapes.

The .geo file is generated deterministically from validated numbers and names;
no user text enters it. gmsh runs as a separate process (CLI only). Physical
surface tags start at 1 and MaterialIDs = tag - 1. Boundaries are grouped by
physical name in our own converter.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from ..schema import Model
from .contract import (LINE, QUAD, QUADRATIC_EDGE, QUADRATIC_QUAD, QUADRATIC_TRIANGLE, TRIANGLE, MeshBundle,
                       grid, region_submesh, submesh)
from .structured import MeshError, check_estimate, default_size, expected_measures


def _f(x: float) -> str:
    return repr(float(x))


class _Geo:
    def __init__(self):
        self.lines: list[str] = []
        self.np = self.nl = self.ns = self.nf = 0

    def point(self, x, y):
        self.np += 1
        self.lines.append(f"Point({self.np}) = {{{_f(x)}, {_f(y)}, 0}};")
        return self.np

    def line(self, a, b):
        self.nl += 1
        self.lines.append(f"Line({self.nl}) = {{{a}, {b}}};")
        return self.nl

    def arc(self, a, c, b):
        self.nl += 1
        self.lines.append(f"Circle({self.nl}) = {{{a}, {c}, {b}}};")
        return self.nl

    def surface(self, *loops):
        ids = []
        for loop in loops:
            self.nl += 1
            self.lines.append(f"Curve Loop({self.nl}) = {{{', '.join(str(c) for c in loop)}}};")
            ids.append(self.nl)
        self.ns += 1
        self.lines.append(f"Plane Surface({self.ns}) = {{{', '.join(str(i) for i in ids)}}};")
        return self.ns

    def field(self, text):
        self.nf += 1
        self.lines.append(text.replace("#", str(self.nf)))
        return self.nf


def _layered(geo: _Geo, x0, x1, ys, names, vertical: bool):
    """Layered rectangle. vertical=True: layers stack in y (rect, axisym); False: along x (strip)."""
    curves: dict[str, list[int]] = {}
    surfaces = []
    if vertical:
        L = [geo.point(x0, y) for y in ys]
        R = [geo.point(x1, y) for y in ys]
        h = [geo.line(L[i], R[i]) for i in range(len(ys))]
        vr = [geo.line(R[i], R[i + 1]) for i in range(len(ys) - 1)]
        vl = [geo.line(L[i], L[i + 1]) for i in range(len(ys) - 1)]
        for i in range(len(ys) - 1):
            surfaces.append(geo.surface([h[i], vr[i], -h[i + 1], -vl[i]]))
        curves["bottom"], curves["top"] = [h[0]], [h[-1]]
        curves["_left"], curves["_right"] = vl, vr
        for i in range(1, len(ys) - 1):
            curves[f"interface_{names[i - 1]}_{names[i]}"] = [h[i]]
    else:
        xs = ys
        B = [geo.point(x, x0) for x in xs]
        T = [geo.point(x, x1) for x in xs]
        v = [geo.line(B[i], T[i]) for i in range(len(xs))]
        hb = [geo.line(B[i], B[i + 1]) for i in range(len(xs) - 1)]
        ht = [geo.line(T[i], T[i + 1]) for i in range(len(xs) - 1)]
        for i in range(len(xs) - 1):
            surfaces.append(geo.surface([hb[i], v[i + 1], -ht[i], -v[i]]))
        curves["left"], curves["right"] = [v[0]], [v[-1]]
        curves["_bottom"], curves["_top"] = hb, ht
        for i in range(1, len(xs) - 1):
            curves[f"interface_{names[i - 1]}_{names[i]}"] = [v[i]]
    return surfaces, curves


def make_geo(model: Model, element: str) -> tuple[str, list[str], list[str]]:
    """Return .geo text, region names (tag order) and boundary/interface names (tag order)."""
    g = model.geometry
    h = model.mesh.size or default_size(model)
    geo = _Geo()
    phys_curves: dict[str, list[int]] = {}
    if g.kind == "rect" and g.segments:
        raise MeshError("boundary segments need the quadrilateral mesh; use element 'quad'")
    if g.kind in ("rect", "axisym_well"):
        x0, x1 = (0.0, g.width) if g.kind == "rect" else (g.well_radius, g.outer_radius)
        ys = np.cumsum([0.0] + [l.thickness for l in g.layers])
        names = [l.name for l in g.layers]
        surfaces, c = _layered(geo, x0, x1, ys, names, vertical=True)
        lname, rname = ("left", "right") if g.kind == "rect" else ("well", "outer")
        phys_curves[lname], phys_curves[rname] = c.pop("_left"), c.pop("_right")
        if len(names) > 1:
            for i, n in enumerate(names):
                phys_curves[f"{lname}_{n}"] = [phys_curves[lname][i]]
                phys_curves[f"{rname}_{n}"] = [phys_curves[rname][i]]
        phys_curves.update(c)
    elif g.kind == "strip":
        xs = np.cumsum([0.0] + [s.thickness for s in g.segments])
        names = [s.name for s in g.segments]
        surfaces, c = _layered(geo, 0.0, g.width, xs, names, vertical=False)
        phys_curves["bottom"], phys_curves["top"] = c.pop("_bottom"), c.pop("_top")
        if len(names) > 1:
            for i, n in enumerate(names):
                phys_curves[f"bottom_{n}"] = [phys_curves["bottom"][i]]
                phys_curves[f"top_{n}"] = [phys_curves["top"][i]]
        phys_curves.update(c)
    elif g.kind == "rect_inclusion":
        W, H, (xc, yc), r = g.width, g.height, g.center, g.radius
        p = [geo.point(0, 0), geo.point(W, 0), geo.point(W, H), geo.point(0, H)]
        b, rt, t, lf = geo.line(p[0], p[1]), geo.line(p[1], p[2]), geo.line(p[2], p[3]), geo.line(p[3], p[0])
        c0 = geo.point(xc, yc)
        q = [geo.point(xc + r, yc), geo.point(xc, yc + r), geo.point(xc - r, yc), geo.point(xc, yc - r)]
        arcs = [geo.arc(q[i], c0, q[(i + 1) % 4]) for i in range(4)]
        s_mat = geo.surface([b, rt, t, lf], arcs)
        s_inc = geo.surface(arcs)
        surfaces, names = [s_mat, s_inc], [g.matrix, g.inclusion]
        phys_curves = {"left": [lf], "right": [rt], "bottom": [b], "top": [t], "inclusion_boundary": arcs}
    else:
        raise MeshError(f"the gmsh engine does not build '{g.kind}'")

    out = geo.lines
    for i, (s, n) in enumerate(zip(surfaces, names), start=1):
        out.append(f'Physical Surface("{n}", {i}) = {{{s}}};')
    curve_names = list(phys_curves)
    for j, n in enumerate(curve_names, start=101):
        out.append(f'Physical Curve("{n}", {j}) = {{{", ".join(str(c) for c in phys_curves[n])}}};')

    # size fields: global size, thresholds near curves, caps inside regions
    fields = [geo.field(f"Field[#] = MathEval; Field[#].F = \"{_f(h)}\";")]
    region_surface = dict(zip(names, surfaces))
    for ref in model.mesh.refinements:
        if ref.target in region_surface:  # region: cap the size inside it
            fields.append(geo.field(
                f"Field[#] = Constant; Field[#].VIn = {_f(ref.size)}; Field[#].VOut = {_f(h)}; "
                f"Field[#].SurfacesList = {{{region_surface[ref.target]}}}; Field[#].IncludeBoundary = 1;"))
        elif ref.target in phys_curves:  # boundary or interface: grow away from it
            d = geo.field(f"Field[#] = Distance; Field[#].CurvesList = "
                          f"{{{', '.join(map(str, phys_curves[ref.target]))}}}; Field[#].Sampling = 200;")
            reach = (h - ref.size) / (ref.growth - 1.0) if ref.growth > 1.0 else 1e30
            fields.append(geo.field(
                f"Field[#] = Threshold; Field[#].InField = {d}; Field[#].SizeMin = {_f(ref.size)}; "
                f"Field[#].SizeMax = {_f(h)}; Field[#].DistMin = 0; Field[#].DistMax = {_f(max(reach, 1e-12))};"))
        else:
            known = sorted(set(phys_curves) | set(region_surface))
            raise MeshError(f"refinement target '{ref.target}' is not a boundary, interface or region "
                            f"(choose from: {', '.join(known)})")
    fmin = geo.field(f"Field[#] = Min; Field[#].FieldsList = {{{', '.join(map(str, fields))}}};")
    out += [f"Background Field = {fmin};",
            "Mesh.MeshSizeExtendFromBoundary = 0;", "Mesh.MeshSizeFromPoints = 0;",
            "Mesh.MeshSizeFromCurvature = 0;", "General.NumThreads = 1;", "Mesh.MaxNumThreads2D = 1;",
            "Mesh.RandomSeed = 1;", "Mesh.SecondOrderIncomplete = 1;"]
    if element == "quad":
        out += ["Mesh.Algorithm = 8;", "Mesh.RecombineAll = 1;", "Mesh.RecombinationAlgorithm = 1;",
                "Mesh.SubdivisionAlgorithm = 1;"]
    else:
        out += ["Mesh.Algorithm = 6;"]
    return "\n".join(out) + "\n", names, curve_names


def gmsh_command() -> list[str]:
    """The gmsh CLI from the pip package, run with this Python (its script has a generic shebang)."""
    script = Path(sys.executable).parent / "gmsh"
    if script.exists():
        return [sys.executable, str(script)]
    exe = shutil.which("gmsh")
    if exe:
        return [exe]
    raise MeshError("gmsh is not installed; install the optional 'mesh-gmsh' extra to build this shape")


# system libraries the gmsh wheel loads on Linux (checked on python:3.12-slim, Debian)
LINUX_GMSH_PACKAGES = "apt-get install libgl1 libglu1-mesa libgomp1 libxcursor1 libxft2 libxinerama1"

_VTK = {"triangle": TRIANGLE, "triangle6": QUADRATIC_TRIANGLE, "quad": QUAD, "quad8": QUADRATIC_QUAD,
        "line": LINE, "line3": QUADRATIC_EDGE}
_EDGES = {3: [(0, 1), (1, 2), (2, 0)], 4: [(0, 1), (1, 2), (2, 3), (3, 0)]}


def run_gmsh(geo_text: str, workdir: Path, order: int, timeout: float = 120) -> Path:
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    geo = workdir / "model.geo"
    geo.write_text(geo_text)
    msh = workdir / "model.msh"
    cmd = gmsh_command() + [str(geo), "-2", "-order", str(order), "-format", "msh22", "-o", str(msh)]
    p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
    (workdir / "gmsh.log").write_text(p.stdout + p.stderr)
    if p.returncode != 0 or not msh.exists() or "Error" in p.stdout + p.stderr:
        missing = re.search(r"(\S+\.so[.\d]*): cannot open shared object file", p.stdout + p.stderr)
        if missing:
            raise MeshError(f"gmsh cannot start: the system library {missing.group(1)} is missing. On Debian or "
                            f"Ubuntu install it with: {LINUX_GMSH_PACKAGES}. Shapes made of rectangles and boxes do "
                            "not need gmsh (use element 'quad').")
        tail = "\n".join((p.stdout + p.stderr).splitlines()[-8:])
        raise MeshError(f"gmsh failed (exit {p.returncode}):\n{tail}")
    return msh


def convert(msh: Path, region_names: list[str], model: Model, order: int) -> MeshBundle:
    import meshio
    m = meshio.read(msh)
    tag_name = {v[0]: k for k, v in m.field_data.items()}
    bulk_parts, mats, line_blocks = [], [], []
    for cb, ph in zip(m.cells, m.cell_data["gmsh:physical"]):
        if cb.type in ("triangle", "triangle6", "quad", "quad8"):
            bulk_parts.append((cb.type, cb.data))
            mats.append(np.asarray(ph) - 1)
        elif cb.type in ("line", "line3"):
            line_blocks.append((cb.type, cb.data, np.asarray(ph)))
    types = {t for t, _ in bulk_parts}
    if len(types) != 1:
        raise MeshError(f"mixed element types from gmsh: {sorted(types)}")
    btype = types.pop()
    conn = np.vstack([c for _, c in bulk_parts])
    mat = np.concatenate(mats).astype(np.int32)
    if mat.min() < 0 or mat.max() >= len(region_names):
        raise MeshError("a gmsh physical surface tag is outside the region list")
    used = np.unique(conn)
    remap = -np.ones(len(m.points), np.int64)
    remap[used] = np.arange(len(used))
    conn = remap[conn]
    bulk = grid(conn, _VTK[btype], m.points[used][:, :2])
    bulk.cell_data["MaterialIDs"] = mat
    ncorner = 3 if btype.startswith("triangle") else 4
    edge2el: dict[tuple[int, int], list[int]] = {}
    for e, c in enumerate(conn):
        for a, b in _EDGES[ncorner]:
            edge2el.setdefault((min(c[a], c[b]), max(c[a], c[b])), []).append(e)
    grouped: dict[str, list[np.ndarray]] = {}
    ltype = None
    for t, lconn, ph in line_blocks:
        ltype = t
        for tag in np.unique(ph):
            grouped.setdefault(tag_name[int(tag)], []).append(remap[lconn[ph == tag]])
    boundaries, interfaces = {}, {}
    for name, parts in grouped.items():
        lc = np.vstack(parts)
        if (lc < 0).any():
            raise MeshError(f"boundary '{name}' uses nodes outside the bulk mesh")
        elems = []
        for a, b in lc[:, :2]:
            owners = edge2el.get((min(a, b), max(a, b)))
            if not owners:
                raise MeshError(f"boundary '{name}' has an edge that belongs to no bulk element")
            elems.append(min(owners, key=lambda e: (mat[e], e)))
        sm = submesh(bulk, lc, _VTK[ltype], np.array(elems))
        (interfaces if name.startswith("interface_") or name == "inclusion_boundary" else boundaries)[name] = sm
    region_meshes = {n: region_submesh(bulk, conn, _VTK[btype], mat == i) for i, n in enumerate(region_names)}
    return MeshBundle(bulk, boundaries, interfaces, {n: i for i, n in enumerate(region_names)}, region_meshes,
                      dim=2, order=order, axisymmetric=model.geometry.kind == "axisym_well", engine="gmsh",
                      expected=expected_measures(model))


def estimate_elements(model: Model, element: str) -> float:
    """Rough element count from areas and sizes: about 2.3 A / h^2 triangles (half as many quads), plus the
    graded bands along refined curves."""
    g, ms = model.geometry, model.mesh
    h = ms.size or default_size(model)
    exp = expected_measures(model)
    caps = {r.target: min(h, r.size) for r in ms.refinements if r.target in exp["regions"]}
    n = sum(a / caps.get(name, h) ** 2 for name, a in exp["regions"].items())
    for r in ms.refinements:
        if r.target in caps or r.size >= h:
            continue
        length = exp["boundaries"].get(r.target) or max(exp["boundaries"].values())
        if r.target == "inclusion_boundary" or r.target.startswith("interface_"):
            length *= 2  # graded on both sides
        gr = r.growth - 1.0
        n += length * (1.0 / r.size - 1.0 / h) / gr if gr > 0 else sum(exp["regions"].values()) / r.size ** 2
    return 2.3 * n / (2.0 if element == "quad" else 1.0)


def build(model: Model, workdir: Path, order: int = 1, element: str = "tri",
          limit: int | None = None) -> MeshBundle:
    if model.geometry.kind == "box":
        raise MeshError("3D boxes use the structured hexahedral engine")
    if model.mesh.divisions:
        raise MeshError("divisions apply to quadrilateral meshes of layered shapes (element 'quad'); triangle "
                        "meshes and the circular inclusion are controlled by size and refinements")
    check_estimate(estimate_elements(model, element), limit, model.mesh.size or default_size(model), 2)
    text, regions, _ = make_geo(model, element)
    msh = run_gmsh(text, workdir, order)
    return convert(msh, regions, model, order)
