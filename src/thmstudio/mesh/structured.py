"""Structured graded quad/hex meshes for the rectangular shapes (G1, G3, G5, G6).

Each axis is split into segments (layers or strip segments). Node spacing
follows a size function: the global size, capped inside refined regions, and
growing geometrically away from refined boundaries and interfaces. Names of
regions and boundaries are set by construction, never inferred.
"""
from __future__ import annotations

import numpy as np

from ..schema import Model, boundaries_of, regions_of
from .contract import (HEXAHEDRON, LINE, QUAD, QUADRATIC_EDGE, QUADRATIC_QUAD, VERTEX, MeshBundle, grid,
                       region_submesh, submesh)


class MeshError(ValueError):
    pass


# ---------------------------------------------------------------- 1D axes

def _size_function(x, h, points, cap):
    s = np.full_like(x, h if cap is None else min(h, cap))
    for p, h0, q in points:
        s = np.minimum(s, h0 + (q - 1.0) * np.abs(x - p))
    return s


def _pieces(a: float, b: float, h: float, points, cap) -> list[tuple[float, float, float, float]]:
    """The size function on [a, b] as linear pieces (x0, x1, alpha, beta) with s = alpha + beta x."""
    c = h if cap is None else min(h, cap)
    lines = [(c, 0.0, -np.inf, np.inf)]
    for p, h0, q in points:
        g = q - 1.0
        lines += [(h0 - g * p, g, p, np.inf), (h0 + g * p, -g, -np.inf, p)]
    brk = {a, b} | {p for p, _, _ in points if a < p < b}
    for i, (a1, b1, _, _) in enumerate(lines):
        for a2, b2, _, _ in lines[i + 1:]:
            if b1 != b2:
                x = (a2 - a1) / (b1 - b2)
                if a < x < b:
                    brk.add(x)
    xs = sorted(brk)
    out = []
    for x0, x1 in zip(xs[:-1], xs[1:]):
        if x1 - x0 <= 1e-14 * max(1.0, abs(x0), abs(x1)):
            continue
        m = 0.5 * (x0 + x1)
        al, be = min(((al, be) for al, be, lo, hi in lines if lo <= m <= hi), key=lambda l: l[0] + l[1] * m)
        out.append((x0, x1, al, be))
    return out


def _piece_integrals(pieces) -> np.ndarray:
    """Exact integral of 1 / size over each piece (number of elements it asks for)."""
    out = []
    for x0, x1, al, be in pieces:
        s0, s1 = al + be * x0, al + be * x1
        out.append((x1 - x0) / s0 if abs(s1 - s0) <= 1e-12 * s0 else np.log(s1 / s0) / be)
    return np.array(out)


def segment_count(a: float, b: float, h: float, points=(), cap=None) -> int:
    return max(1, int(round(float(_piece_integrals(_pieces(a, b, h, points, cap)).sum()))))


def segment_nodes(a: float, b: float, h: float, points=(), cap=None, n: int | None = None) -> np.ndarray:
    """Nodes from a to b. n elements if given, else as many as the size function asks for.
    Nodes are placed at equal steps of the exact integral of 1 / size, so the first element next to a
    refinement has about the requested size and neighbours grow by about the requested factor."""
    pieces = _pieces(a, b, h, points, cap)
    w = _piece_integrals(pieces)
    F = np.concatenate([[0.0], np.cumsum(w)])
    if n is None:
        n = max(1, int(round(F[-1])))
    target = np.linspace(0.0, F[-1], n + 1)
    k = np.clip(np.searchsorted(F, target, side="right") - 1, 0, len(pieces) - 1)
    nodes = np.empty(n + 1)
    for j, (t, i) in enumerate(zip(target, k)):
        x0, x1, al, be = pieces[i]
        s0, d = al + be * x0, t - F[i]
        nodes[j] = x0 + d * s0 if abs(be) * (x1 - x0) <= 1e-12 * s0 else (s0 * np.exp(be * d) - al) / be
    nodes[0], nodes[-1] = a, b
    return np.maximum.accumulate(np.clip(nodes, a, b))


def axis_counts(bounds: list[float], h: float, points, caps: list[float | None],
                seg_div: list[int | None], total: int | None) -> list[int]:
    """Elements per segment. A requested total is shared over the free segments by their size-function
    weights, after one element is reserved for each, so the total is never exceeded."""
    nseg = len(bounds) - 1
    counts = list(seg_div)
    if total is not None and any(c is None for c in counts):
        free = [i for i in range(nseg) if counts[i] is None]
        rest = total - sum(c for c in counts if c is not None)
        if rest < len(free):
            raise MeshError(f"the total number of divisions ({total}) is smaller than the number of layers "
                            f"({nseg}); each layer needs at least one element")
        w = np.array([float(_piece_integrals(_pieces(bounds[i], bounds[i + 1], h, points, caps[i])).sum())
                      for i in free])
        share = (rest - len(free)) * w / w.sum()
        base = np.floor(share).astype(int)
        for k in np.argsort(-(share - base))[: rest - len(free) - int(base.sum())]:
            base[k] += 1
        for i, c in zip(free, base):
            counts[i] = 1 + int(c)
    return [c if c is not None else segment_count(bounds[i], bounds[i + 1], h, points, caps[i])
            for i, c in enumerate(counts)]


def axis_nodes(bounds: list[float], h: float, points, caps: list[float | None],
               seg_div: list[int | None], total: int | None,
               counts: list[int] | None = None) -> tuple[np.ndarray, list[int]]:
    """Concatenate segment nodes. Returns nodes and the element index where each segment starts."""
    counts = counts or axis_counts(bounds, h, points, caps, seg_div, total)
    parts, starts = [], [0]
    for i in range(len(bounds) - 1):
        seg = segment_nodes(bounds[i], bounds[i + 1], h, points, caps[i], counts[i])
        parts.append(seg if i == 0 else seg[1:])
        starts.append(starts[-1] + len(seg) - 1)
    return np.concatenate(parts), starts


def check_estimate(n: float, limit: int | None, h: float, dim: int):
    """Refuse before building when the element count would be far above the limit."""
    if limit is not None and n > limit:
        raise MeshError(f"too many elements: about {int(n):,} would be built, above {limit:,}; use a size of at "
                        f"least {h * 1.1 * (n / limit) ** (1.0 / dim):.3g} m, fewer refinements or fewer divisions "
                        "(larger models are a commercial service: contact GeoAI Alignment)")


# ---------------------------------------------------------------- geometry -> axes

def _axes(model: Model, h: float):
    """Per axis: (name, segment bounds, segment names). The stacking axis carries the regions."""
    g = model.geometry
    if g.kind == "rect":
        H = np.cumsum([0.0] + [l.thickness for l in g.layers])
        xb = sorted({0.0, float(g.width)} | {float(v) for sg in g.segments for v in (sg.start, sg.end)})
        return [("x", xb, [None] * (len(xb) - 1)), ("y", list(H), [l.name for l in g.layers])], 1
    if g.kind == "strip":
        X = np.cumsum([0.0] + [s.thickness for s in g.segments])
        return [("x", list(X), [s.name for s in g.segments]), ("y", [0.0, g.width], [None])], 0
    if g.kind == "axisym_well":
        H = np.cumsum([0.0] + [l.thickness for l in g.layers])
        return [("r", [g.well_radius, g.outer_radius], [None]), ("z", list(H), [l.name for l in g.layers])], 1
    if g.kind == "box":
        H = np.cumsum([0.0] + [l.thickness for l in g.layers])
        return [("x", [0.0, g.length_x], [None]), ("y", [0.0, g.length_y], [None]),
                ("z", list(H), [l.name for l in g.layers])], 2
    raise MeshError(f"the structured engine does not build '{g.kind}'")


def _targets(model: Model) -> dict[str, tuple[int, float]]:
    """Refinement target name -> (axis index, coordinate)."""
    g = model.geometry
    axes, stack = _axes(model, 1.0)
    out = {}
    names = {"rect": (("left", 0, 0), ("right", 0, 1), ("bottom", 1, 0), ("top", 1, 1)),
             "strip": (("left", 0, 0), ("right", 0, 1), ("bottom", 1, 0), ("top", 1, 1)),
             "axisym_well": (("well", 0, 0), ("outer", 0, 1), ("bottom", 1, 0), ("top", 1, 1)),
             "box": (("left", 0, 0), ("right", 0, 1), ("front", 1, 0), ("back", 1, 1),
                     ("bottom", 2, 0), ("top", 2, 1))}[g.kind]
    for name, ax, end in names:
        out[name] = (ax, axes[ax][1][0] if end == 0 else axes[ax][1][-1])
    bounds, segs = axes[stack][1], axes[stack][2]
    for i in range(len(segs) - 1):
        out[f"interface_{segs[i]}_{segs[i + 1]}"] = (stack, bounds[i + 1])
    return out


def _segment_targets(model: Model) -> dict[str, list[tuple[int, float]]]:
    g = model.geometry
    return {sg.name: [(0, sg.start), (0, sg.end)] for sg in getattr(g, "segments", [])} if g.kind == "rect" else {}


def _extents(g) -> list[float]:
    if g.kind == "rect":
        return [g.width, sum(l.thickness for l in g.layers)]
    if g.kind == "strip":
        return [sum(s.thickness for s in g.segments), g.width]
    if g.kind == "axisym_well":
        return [g.outer_radius - g.well_radius, sum(l.thickness for l in g.layers)]
    if g.kind == "box":
        return [g.length_x, g.length_y, sum(l.thickness for l in g.layers)]
    if g.kind == "rect_inclusion":
        return [g.width, g.height]
    if g.kind == "axisym_source":
        return [g.outer_radius, g.height]
    raise MeshError(f"no mesh size rule for '{g.kind}'")


def default_size(model: Model) -> float:
    """Global element size when the user gives none: 1/50 of the largest extent (1/20 for 3D boxes)."""
    return max(_extents(model.geometry)) / (20.0 if model.geometry.kind == "box" else 50.0)


def build_axes(model: Model, limit: int | None = None) -> tuple[list[np.ndarray], list[list[int]], int, list[str]]:
    """Graded node coordinates per axis. Boundary and interface refinements grade along the axis normal to them;
    a region refinement caps the size only along the stacking axis (layer thickness direction)."""
    ms = model.mesh
    h = ms.size or default_size(model)
    axes, stack = _axes(model, h)
    targets = _targets(model)
    region_names = set(axes[stack][2])
    points = [[] for _ in axes]
    caps = [[None] * (len(a[1]) - 1) for a in axes]
    seg_t = _segment_targets(model)
    for r in ms.refinements:
        if r.target in seg_t:  # refine around both ends of a boundary segment
            for ax, pos in seg_t[r.target]:
                points[ax].append((pos, r.size, r.growth))
        elif r.target in targets:
            ax, pos = targets[r.target]
            points[ax].append((pos, r.size, r.growth))
        elif r.target in region_names:
            i = axes[stack][2].index(r.target)
            caps[stack][i] = r.size if caps[stack][i] is None else min(caps[stack][i], r.size)
        else:
            raise MeshError(f"refinement target '{r.target}' is not a boundary, interface or region "
                            f"(choose from: {', '.join(sorted(set(targets) | region_names | set(seg_t)))})")
    known = {a[0] for a in axes} | region_names
    for k in ms.divisions:
        if k not in known:
            raise MeshError(f"divisions key '{k}' is not an axis or region (choose from: {', '.join(sorted(known))})")
    counts = []
    for i, (name, bounds, segs) in enumerate(axes):
        seg_div = [ms.divisions.get(s) if s else None for s in segs]
        total = ms.divisions.get(name)
        if model.geometry.kind == "strip" and name == "y" and total is None:
            total = 1  # a strip is one element wide unless the user asks otherwise
        if len(segs) == 1 and total is not None:
            seg_div, total = [total], None
        counts.append(axis_counts(bounds, h, points[i], caps[i], seg_div, total))
    check_estimate(float(np.prod([sum(c) for c in counts])), limit, h, len(axes))
    nodes, starts = [], []
    for i, (name, bounds, segs) in enumerate(axes):
        xs, st = axis_nodes(bounds, h, points[i], caps[i], [None] * len(segs), None, counts[i])
        nodes.append(xs)
        starts.append(st)
    return nodes, starts, stack, axes[stack][2]


# ---------------------------------------------------------------- 2D

def _quad_cells(xs, ys, order):
    nx, ny = len(xs) - 1, len(ys) - 1
    if order == 1:
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        pts = np.c_[X.ravel(), Y.ravel()]
        I, J = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
        I, J = I.ravel(), J.ravel()
        nid = lambda i, j: i * (ny + 1) + j
        cells = np.c_[nid(I, J), nid(I + 1, J), nid(I + 1, J + 1), nid(I, J + 1)]
        return pts, cells
    xf = np.empty(2 * nx + 1); xf[::2] = xs; xf[1::2] = 0.5 * (xs[:-1] + xs[1:])
    yf = np.empty(2 * ny + 1); yf[::2] = ys; yf[1::2] = 0.5 * (ys[:-1] + ys[1:])
    keep = -np.ones((2 * nx + 1, 2 * ny + 1), np.int64)
    Ii, Jj = np.meshgrid(np.arange(2 * nx + 1), np.arange(2 * ny + 1), indexing="ij")
    mask = ~((Ii % 2 == 1) & (Jj % 2 == 1))
    keep[mask] = np.arange(mask.sum())
    pts = np.c_[xf[Ii[mask]], yf[Jj[mask]]]
    I, J = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    I, J = 2 * I.ravel(), 2 * J.ravel()
    k = lambda a, b: keep[a, b]
    cells = np.c_[k(I, J), k(I + 2, J), k(I + 2, J + 2), k(I, J + 2),
                  k(I + 1, J), k(I + 2, J + 1), k(I + 1, J + 2), k(I, J + 1)]
    return pts, cells


# local corner pair and mid node of each quad side (VTK order)
_SIDES2D = {"bottom": ((0, 1), 4), "right": ((1, 2), 5), "top": ((2, 3), 6), "left": ((3, 0), 7)}


def _side_mesh(bulk, cells, elems, side, order):
    (a, b), m = _SIDES2D[side]
    local = cells[elems][:, [a, b, m]] if order == 2 else cells[elems][:, [a, b]]
    return submesh(bulk, local, QUADRATIC_EDGE if order == 2 else LINE, elems)


def build_2d(model: Model, order: int, limit: int | None = None) -> MeshBundle:
    g = model.geometry
    (xs, ys), (sx, sy), stack, segs = build_axes(model, limit)
    nx, ny = len(xs) - 1, len(ys) - 1
    pts, cells = _quad_cells(xs, ys, order)
    bulk = grid(cells, QUADRATIC_QUAD if order == 2 else QUAD, pts)
    I = np.repeat(np.arange(nx), ny)
    J = np.tile(np.arange(ny), nx)
    along, starts = (J, sy) if stack == 1 else (I, sx)
    mat = np.searchsorted(np.array(starts[1:-1]), along, side="right").astype(np.int32)
    bulk.cell_data["MaterialIDs"] = mat
    eid = lambda i, j: i * ny + j
    side_elems = {"bottom": eid(np.arange(nx), 0), "top": eid(np.arange(nx), ny - 1),
                  "left": eid(0, np.arange(ny)), "right": eid(nx - 1, np.arange(ny))}
    names = {"left": "left", "right": "right", "bottom": "bottom", "top": "top"}
    if g.kind == "axisym_well":
        names = {"left": "well", "right": "outer", "bottom": "bottom", "top": "top"}
    boundaries = {names[s]: _side_mesh(bulk, cells, e, s, order) for s, e in side_elems.items()}
    if len(segs) > 1:
        sides = ("left", "right") if stack == 1 else ("bottom", "top")
        for s in sides:
            e = side_elems[s]
            for r, name in enumerate(segs):
                sel = e[mat[e] == r]
                boundaries[f"{names[s]}_{name}"] = _side_mesh(bulk, cells, sel, s, order)
    interfaces = {}
    for r in range(len(segs) - 1):
        k = starts[r + 1] - 1  # last element row of the lower segment
        elems = eid(np.arange(nx), k) if stack == 1 else eid(k, np.arange(ny))
        interfaces[f"interface_{segs[r]}_{segs[r + 1]}"] = _side_mesh(
            bulk, cells, elems, "top" if stack == 1 else "right", order)
    if g.kind == "rect":
        xc = 0.5 * (xs[I] + xs[I + 1])
        for sg in g.segments:
            e = side_elems[sg.side]
            sel = e[(xc[e] > sg.start) & (xc[e] < sg.end)]
            boundaries[sg.name] = _side_mesh(bulk, cells, sel, sg.side, order)
    ctype = QUADRATIC_QUAD if order == 2 else QUAD
    region_meshes = {name: region_submesh(bulk, cells, ctype, mat == r) for r, name in enumerate(segs)}
    b = MeshBundle(bulk, boundaries, interfaces, {n: i for i, n in enumerate(segs)}, region_meshes,
                   dim=2, order=order, axisymmetric=g.kind == "axisym_well", engine="structured",
                   expected=expected_measures(model))
    if g.kind == "rect":
        corners = {"corner_bottom_left": (xs[0], ys[0], eid(0, 0)), "corner_bottom_right": (xs[-1], ys[0], eid(nx - 1, 0)),
                   "corner_top_left": (xs[0], ys[-1], eid(0, ny - 1)), "corner_top_right": (xs[-1], ys[-1], eid(nx - 1, ny - 1))}
        b.point_meshes = {n: point_mesh(bulk, x, y, e) for n, (x, y, e) in corners.items()}
    return b


def point_mesh(bulk, x, y, element):
    """One-vertex mesh at a bulk node (for point conditions and point sources)."""
    d = np.hypot(bulk.points[:, 0] - x, bulk.points[:, 1] - y)
    node = int(np.argmin(d))
    if d[node] > 1e-9 * max(1.0, abs(x), abs(y)):
        raise MeshError(f"no mesh node at ({x}, {y})")
    pm = grid(np.array([[0]]), VERTEX, bulk.points[[node]])
    pm.point_data["bulk_node_ids"] = np.array([node], np.uint64)
    pm.cell_data["bulk_element_ids"] = np.array([element], np.uint64)
    return pm


# ---------------------------------------------------------------- 3D

_FACES3D = {"bottom": (0, 3, 2, 1), "top": (4, 5, 6, 7), "front": (0, 1, 5, 4), "back": (3, 7, 6, 2),
            "left": (0, 4, 7, 3), "right": (1, 2, 6, 5)}


def build_3d(model: Model, order: int, limit: int | None = None) -> MeshBundle:
    if order != 1:
        raise MeshError("3D boxes are built with linear hexahedra only in v0.1")
    (xs, ys, zs), (_, _, sz), _, segs = build_axes(model, limit)
    nx, ny, nz = len(xs) - 1, len(ys) - 1, len(zs) - 1
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.c_[X.ravel(), Y.ravel(), Z.ravel()]
    nid = lambda i, j, k: (i * (ny + 1) + j) * (nz + 1) + k
    I, J, K = (a.ravel() for a in np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"))
    cells = np.c_[nid(I, J, K), nid(I + 1, J, K), nid(I + 1, J + 1, K), nid(I, J + 1, K),
                  nid(I, J, K + 1), nid(I + 1, J, K + 1), nid(I + 1, J + 1, K + 1), nid(I, J + 1, K + 1)]
    bulk = grid(cells, HEXAHEDRON, pts)
    mat = np.searchsorted(np.array(sz[1:-1]), K, side="right").astype(np.int32)
    bulk.cell_data["MaterialIDs"] = mat
    e = np.arange(len(cells))
    sel = {"bottom": K == 0, "top": K == nz - 1, "front": J == 0, "back": J == ny - 1,
           "left": I == 0, "right": I == nx - 1}
    boundaries = {s: submesh(bulk, cells[sel[s]][:, list(_FACES3D[s])], QUAD, e[sel[s]]) for s in _FACES3D}
    interfaces = {}
    for r in range(len(segs) - 1):
        m = K == sz[r + 1] - 1
        interfaces[f"interface_{segs[r]}_{segs[r + 1]}"] = submesh(bulk, cells[m][:, list(_FACES3D["top"])], QUAD, e[m])
    region_meshes = {name: region_submesh(bulk, cells, HEXAHEDRON, mat == r) for r, name in enumerate(segs)}
    return MeshBundle(bulk, boundaries, interfaces, {n: i for i, n in enumerate(segs)}, region_meshes,
                      dim=3, order=1, axisymmetric=False, engine="structured", expected=expected_measures(model))


# ---------------------------------------------------------------- G4: axisymmetric source

def _g4_breaks(g):
    """r and z breakpoints of the tensor grid (source centre at r = 0, z = 0)."""
    rs = [0.0]
    if g.source == "canister":
        rs.append(g.canister_radius)
    if g.buffer_radius:
        rs.append(g.buffer_radius)
    rs.append(g.outer_radius)
    halves = [0.0]
    if g.source == "canister":
        halves.append(g.canister_length / 2)
    if g.buffer_length:
        halves.append(g.buffer_length / 2)
    top = g.height if g.symmetric else g.height / 2
    zs = halves + [top] if g.symmetric else sorted({-top, top} | {s * h for h in halves for s in (-1, 1)})
    return rs, zs


def _g4_targets(g):
    """Refinement target -> list of (axis, coordinate)."""
    rs, zs = _g4_breaks(g)
    t = {"axis": [(0, 0.0)], "outer": [(0, g.outer_radius)], "top": [(1, zs[-1])], "bottom": [(1, zs[0])]}
    if g.source == "point":
        t["source"] = [(0, 0.0), (1, 0.0)]
    else:
        L = g.canister_length / 2
        t["canister_surface"] = [(0, g.canister_radius), (1, L)] + ([] if g.symmetric else [(1, -L)])
    if g.buffer_radius:
        B = g.buffer_length / 2
        t["buffer_rock"] = [(0, g.buffer_radius), (1, B)] + ([] if g.symmetric else [(1, -B)])
    return t


def _g4_region(g, rc, zc):
    mat = np.zeros(len(rc), np.int32)
    names = [g.rock]
    if g.buffer_radius:
        names.append(g.buffer)
    if g.source == "canister":
        names.append(g.canister)
    from ..schema import regions_of
    order = regions_of(g)
    if g.buffer_radius:
        mat[(rc < g.buffer_radius) & (np.abs(zc) < g.buffer_length / 2)] = order.index(g.buffer)
    if g.source == "canister":
        mat[(rc < g.canister_radius) & (np.abs(zc) < g.canister_length / 2)] = order.index(g.canister)
    return mat


def build_g4(model: Model, order: int, limit: int | None = None) -> MeshBundle:
    g, ms = model.geometry, model.mesh
    rs, zs = _g4_breaks(g)
    h = ms.size or default_size(model)
    targets = _g4_targets(g)
    from ..schema import regions_of
    regions = regions_of(g)
    pts_r, pts_z = [], []
    caps = {"r": [None] * (len(rs) - 1), "z": [None] * (len(zs) - 1)}
    for ref in ms.refinements:
        if ref.target in targets:
            for ax, pos in targets[ref.target]:
                (pts_r if ax == 0 else pts_z).append((pos, ref.size, ref.growth))
        elif ref.target in regions and ref.target != g.rock:
            if ref.target == g.canister:
                rmax, zh = g.canister_radius, g.canister_length / 2
            else:
                rmax, zh = g.buffer_radius, g.buffer_length / 2
            for i in range(len(rs) - 1):
                if rs[i + 1] <= rmax + 1e-12:
                    caps["r"][i] = ref.size
            for i in range(len(zs) - 1):
                if abs(zs[i]) <= zh + 1e-12 and abs(zs[i + 1]) <= zh + 1e-12:
                    caps["z"][i] = ref.size
        else:
            raise MeshError(f"refinement target '{ref.target}' is not a boundary, interface, point or region "
                            f"(choose from: {', '.join(sorted(set(targets) | set(regions)))})")
    for k in ms.divisions:
        if k not in ("r", "z"):
            raise MeshError(f"divisions key '{k}' is not an axis (choose from: r, z)")
    cr = axis_counts(rs, h, pts_r, caps["r"], [None] * (len(rs) - 1), ms.divisions.get("r"))
    cz = axis_counts(zs, h, pts_z, caps["z"], [None] * (len(zs) - 1), ms.divisions.get("z"))
    check_estimate(float(sum(cr) * sum(cz)), limit, h, 2)
    xs, _ = axis_nodes(rs, h, pts_r, caps["r"], [None] * (len(rs) - 1), None, cr)
    ys, _ = axis_nodes(zs, h, pts_z, caps["z"], [None] * (len(zs) - 1), None, cz)
    nx, ny = len(xs) - 1, len(ys) - 1
    pts, cells = _quad_cells(xs, ys, order)
    ctype = QUADRATIC_QUAD if order == 2 else QUAD
    bulk = grid(cells, ctype, pts)
    I = np.repeat(np.arange(nx), ny)
    J = np.tile(np.arange(ny), nx)
    rc, zc = 0.5 * (xs[I] + xs[I + 1]), 0.5 * (ys[J] + ys[J + 1])
    mat = _g4_region(g, rc, zc)
    bulk.cell_data["MaterialIDs"] = mat
    eid = lambda i, j: i * ny + j
    side_elems = {"bottom": eid(np.arange(nx), 0), "top": eid(np.arange(nx), ny - 1),
                  "left": eid(0, np.arange(ny)), "right": eid(nx - 1, np.arange(ny))}
    names = {"left": "axis", "right": "outer", "bottom": "bottom", "top": "top"}
    boundaries = {names[sd]: _side_mesh(bulk, cells, e, sd, order) for sd, e in side_elems.items()}
    # interfaces from cell adjacency: edges of 'inner' cells facing other cells
    M = mat.reshape(nx, ny)
    interfaces = {}
    groups = []
    if g.source == "canister":
        groups.append(("canister_surface", M == regions.index(g.canister)))
    if g.buffer_radius:
        inner = (M == regions.index(g.buffer)) | ((M == regions.index(g.canister)) if g.source == "canister" else False)
        groups.append(("buffer_rock", inner))
    for name, inside in groups:
        parts = []
        for side, (di, dj) in (("right", (1, 0)), ("left", (-1, 0)), ("top", (0, 1)), ("bottom", (0, -1))):
            ii, jj = np.nonzero(inside)
            ni, nj = ii + di, jj + dj
            ok = (ni >= 0) & (ni < nx) & (nj >= 0) & (nj < ny)
            face = np.zeros(len(ii), bool)
            face[ok] = ~inside[ni[ok], nj[ok]]
            if face.any():
                (a, b), m = _SIDES2D[side]
                e = eid(ii[face], jj[face])
                parts.append((cells[e][:, [a, b, m]] if order == 2 else cells[e][:, [a, b]], e))
        lc = np.vstack([p[0] for p in parts])
        el = np.concatenate([p[1] for p in parts])
        interfaces[name] = submesh(bulk, lc, QUADRATIC_EDGE if order == 2 else LINE, el)
    point_meshes = {}
    if g.source == "point":
        j0 = int(np.argmin(np.abs(ys)))
        node = int(np.flatnonzero((np.abs(bulk.points[:, 0]) < 1e-12) & (np.abs(bulk.points[:, 1] - ys[j0]) < 1e-12))[0])
        e0 = eid(0, j0 if j0 < ny else ny - 1)
        pm = grid(np.array([[0]]), VERTEX, bulk.points[[node]])
        pm.point_data["bulk_node_ids"] = np.array([node], np.uint64)
        pm.cell_data["bulk_element_ids"] = np.array([e0], np.uint64)
        point_meshes["source"] = pm
    region_meshes = {n: region_submesh(bulk, cells, ctype, mat == i) for i, n in enumerate(regions)}
    b = MeshBundle(bulk, boundaries, interfaces, {n: i for i, n in enumerate(regions)}, region_meshes,
                   dim=2, order=order, axisymmetric=True, engine="structured", expected=expected_measures(model))
    b.point_meshes = point_meshes
    return b


def build(model: Model, order: int = 1, limit: int | None = None) -> MeshBundle:
    """limit: refuse before building when the estimated element count is above it."""
    if model.geometry.kind == "box":
        return build_3d(model, order, limit)
    if model.geometry.kind == "axisym_source":
        return build_g4(model, order, limit)
    return build_2d(model, order, limit)


# ---------------------------------------------------------------- analytic measures

def expected_measures(model: Model) -> dict[str, dict[str, float]]:
    """Region areas (2D, r-z plane for axisymmetric) or volumes (3D) and boundary lengths or areas."""
    import math
    g = model.geometry
    reg, bnd = {}, {}
    if g.kind == "rect":
        for sg in g.segments:
            bnd[sg.name] = sg.end - sg.start
    if g.kind in ("rect", "axisym_well"):
        w = g.width if g.kind == "rect" else g.outer_radius - g.well_radius
        for l in g.layers:
            reg[l.name] = w * l.thickness
        H = sum(l.thickness for l in g.layers)
        s = ("left", "right") if g.kind == "rect" else ("well", "outer")
        bnd.update({s[0]: H, s[1]: H, "bottom": w, "top": w})
        if len(g.layers) > 1:
            for side in s:
                for l in g.layers:
                    bnd[f"{side}_{l.name}"] = l.thickness
    elif g.kind == "strip":
        for sgm in g.segments:
            reg[sgm.name] = g.width * sgm.thickness
        L = sum(sgm.thickness for sgm in g.segments)
        bnd.update({"left": g.width, "right": g.width, "bottom": L, "top": L})
        if len(g.segments) > 1:
            for side in ("bottom", "top"):
                for sgm in g.segments:
                    bnd[f"{side}_{sgm.name}"] = sgm.thickness
    elif g.kind == "box":
        for l in g.layers:
            reg[l.name] = g.length_x * g.length_y * l.thickness
        H = sum(l.thickness for l in g.layers)
        bnd.update({"bottom": g.length_x * g.length_y, "top": g.length_x * g.length_y,
                    "front": g.length_x * H, "back": g.length_x * H, "left": g.length_y * H, "right": g.length_y * H})
    elif g.kind == "axisym_source":
        rs, zs = _g4_breaks(g)
        H = zs[-1] - zs[0]
        f = 0.5 if g.symmetric else 1.0
        can = g.canister_radius * g.canister_length * f if g.source == "canister" else 0.0
        buf = g.buffer_radius * g.buffer_length * f - can if g.buffer_radius else 0.0
        reg[g.rock] = g.outer_radius * H - can - buf
        if g.source == "canister":
            reg[g.canister] = can
        if g.buffer_radius:
            reg[g.buffer] = buf
        bnd = {"axis": H, "outer": H, "bottom": g.outer_radius, "top": g.outer_radius}
        if g.source == "canister":
            bnd["canister_surface"] = g.canister_radius * (1 if g.symmetric else 2) + g.canister_length * f
        if g.buffer_radius:
            bnd["buffer_rock"] = g.buffer_radius * (1 if g.symmetric else 2) + g.buffer_length * f
    elif g.kind == "rect_inclusion":
        a = math.pi * g.radius ** 2
        reg = {g.matrix: g.width * g.height - a, g.inclusion: a}
        bnd = {"left": g.height, "right": g.height, "bottom": g.width, "top": g.width,
               "inclusion_boundary": 2 * math.pi * g.radius}
    assert set(bnd) - {"inclusion_boundary", "canister_surface", "buffer_rock"} <= set(boundaries_of(g)), \
        "expected measures out of sync"
    assert set(reg) == set(regions_of(g))
    return {"regions": reg, "boundaries": bnd}
