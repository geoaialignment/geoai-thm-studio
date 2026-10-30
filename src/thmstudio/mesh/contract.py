"""Output contract shared by both mesh engines.

A MeshBundle holds the bulk mesh (MaterialIDs from 0), the named boundary
meshes used for conditions, internal interfaces (extraction only) and region
meshes (for volumetric sources). Boundary, interface and region meshes carry
bulk_node_ids and bulk_element_ids.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyvista as pv

# VTK cell types used here
VERTEX, LINE, TRIANGLE, QUAD, HEXAHEDRON = 1, 3, 5, 9, 12
QUADRATIC_EDGE, QUADRATIC_TRIANGLE, QUADRATIC_QUAD = 21, 22, 23
CORNERS = {LINE: 2, TRIANGLE: 3, QUAD: 4, HEXAHEDRON: 8, QUADRATIC_EDGE: 2, QUADRATIC_TRIANGLE: 3,
           QUADRATIC_QUAD: 4, VERTEX: 1}
NAMES = {LINE: "Line2", TRIANGLE: "Tri3", QUAD: "Quad4", HEXAHEDRON: "Hex8", QUADRATIC_EDGE: "Line3",
         QUADRATIC_TRIANGLE: "Tri6", QUADRATIC_QUAD: "Quad8", VERTEX: "Point"}


def grid(cells: np.ndarray, celltype: int, points: np.ndarray) -> pv.UnstructuredGrid:
    cells = np.asarray(cells, dtype=np.int64)
    k = cells.shape[1]
    flat = np.c_[np.full(len(cells), k, dtype=np.int64), cells].ravel()
    pts = np.asarray(points, dtype=float)
    if pts.shape[1] == 2:
        pts = np.c_[pts, np.zeros(len(pts))]
    return pv.UnstructuredGrid(flat, np.full(len(cells), celltype, np.uint8), pts)


def submesh(bulk: pv.UnstructuredGrid, local_cells: np.ndarray, celltype: int,
            bulk_elements: np.ndarray) -> pv.UnstructuredGrid:
    """Mesh made of bulk node ids (local_cells refer to bulk nodes) with bulk ids attached."""
    local_cells = np.asarray(local_cells, dtype=np.int64)
    ids, inv = np.unique(local_cells.ravel(), return_inverse=True)
    g = grid(inv.reshape(local_cells.shape), celltype, bulk.points[ids])
    g.point_data["bulk_node_ids"] = ids.astype(np.uint64)
    g.cell_data["bulk_element_ids"] = np.asarray(bulk_elements, dtype=np.uint64)
    return g


def region_submesh(bulk: pv.UnstructuredGrid, cells: np.ndarray, celltype: int, mask: np.ndarray):
    return submesh(bulk, cells[mask], celltype, np.flatnonzero(mask))


@dataclass
class MeshBundle:
    bulk: pv.UnstructuredGrid
    boundaries: dict[str, pv.UnstructuredGrid]
    interfaces: dict[str, pv.UnstructuredGrid]
    regions: dict[str, int]                       # region name -> MaterialID
    region_meshes: dict[str, pv.UnstructuredGrid]
    dim: int
    order: int
    axisymmetric: bool
    engine: str
    expected: dict[str, dict[str, float]] = field(default_factory=dict)  # 'regions'/'boundaries' -> measure
    files: dict[str, str] = field(default_factory=dict)
    point_meshes: dict[str, pv.UnstructuredGrid] = field(default_factory=dict)  # named points (sources)

    @property
    def cell_type(self) -> str:
        return NAMES[int(self.bulk.celltypes[0])]

    def summary(self) -> dict:
        return {"engine": self.engine, "elements": int(self.bulk.n_cells), "nodes": int(self.bulk.n_points),
                "element_type": self.cell_type, "order": self.order, "dimension": self.dim,
                "axisymmetric": self.axisymmetric, "regions": dict(self.regions),
                "boundaries": {k: int(v.n_cells) for k, v in self.boundaries.items()},
                "interfaces": sorted(self.interfaces), "points": sorted(self.point_meshes)}

    def write(self, outdir: Path, stem: str = "mesh") -> dict[str, str]:
        """Write VTUs (binary, uncompressed for stable hashes). Returns logical name -> file name."""
        outdir.mkdir(parents=True, exist_ok=True)
        files = {"bulk": f"{stem}.vtu"}
        self.bulk.save(outdir / files["bulk"], binary=True)
        for kind, meshes in (("boundary", self.boundaries), ("interface", self.interfaces),
                             ("region", self.region_meshes), ("point", self.point_meshes)):
            for name, m in meshes.items():
                fn = f"{stem}_{kind}_{name}.vtu"
                m.save(outdir / fn, binary=True)
                files[f"{kind}:{name}"] = fn
        self.files = files
        return files

    def file_hash(self, outdir: Path) -> str:
        h = hashlib.sha256()
        for key in sorted(self.files):
            h.update(key.encode())
            h.update((outdir / self.files[key]).read_bytes())
        return h.hexdigest()[:16]
