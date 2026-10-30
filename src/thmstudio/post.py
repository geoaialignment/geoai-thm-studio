"""Post-processing: read outputs, extract values at points and lines, derive head."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyvista as pv

from .runner import read_pvd
from .schema import Model, vertical_axis
from .units import G


@dataclass
class Results:
    rundir: Path
    outputs: list[tuple[float, str]]
    model: Model

    @classmethod
    def load(cls, rundir: Path, model: Model) -> "Results":
        pvd = sorted(Path(rundir).glob("*.pvd"))
        if not pvd:
            raise FileNotFoundError(f"no results in {rundir}")
        return cls(Path(rundir), read_pvd(pvd[0]), model)

    @property
    def times(self) -> np.ndarray:
        return np.array([t for t, _ in self.outputs])

    def mesh_at(self, t: float) -> pv.UnstructuredGrid:
        i = int(np.argmin(np.abs(self.times - t)))
        if abs(self.times[i] - t) > 1e-9 * max(1.0, abs(t)):
            raise KeyError(f"no output at t = {t:g} s (outputs: {', '.join(f'{x:g}' for x in self.times)})")
        return _read(self.rundir / self.outputs[i][1])

    COMPONENTS = {"x": 0, "r": 0, "y": 1, "z": 1, "xx": 0, "rr": 0, "yy": 1, "zz": 2, "tt": 2, "xy": 3, "rz": 3}

    def select_component(self, name: str, component: str):
        """Later calls of field(name) return one component (vectors: x/y or r/z; stress: xx, yy, zz, xy)."""
        c = component.strip().lower()
        if c not in self.COMPONENTS:
            raise KeyError(f"unknown component '{component}' (use {', '.join(self.COMPONENTS)})")
        idx = self.COMPONENTS[c]
        if name == "displacement" and len(c) == 1 and c in "zy" and self.model and self.model.geometry.kind == "box":
            idx = {"y": 1, "z": 2}[c]
        if name == "sigma" and self.model and self.model.geometry.kind in ("axisym_well", "axisym_source"):
            idx = {"rr": 0, "zz": 1, "tt": 2, "rz": 3}.get(c, idx)
        self._component = (name, idx)

    def field(self, mesh: pv.UnstructuredGrid, name: str) -> np.ndarray:
        sel = getattr(self, "_component", None)
        if sel and sel[0] == name:
            self._component = None
            v = self.field(mesh, name)
            self._component = sel
            return v[:, sel[1]]
        if name == "head":
            return head(mesh, self.model)
        # on quadratic meshes, order-1 variables are only defined at corner nodes; OGS writes the
        # values interpolated to all nodes as <name>_interpolated
        if f"{name}_interpolated" in mesh.point_data:
            return np.asarray(mesh.point_data[f"{name}_interpolated"])
        if name in mesh.point_data:
            return np.asarray(mesh.point_data[name])
        raise KeyError(f"no field '{name}' (available: {', '.join(mesh.point_data)})")

    def at_points(self, t: float, name: str, points: np.ndarray) -> np.ndarray:
        m = self.mesh_at(t)
        m = m.copy()
        m.point_data["_v"] = self.field(m, name)
        pts = np.asarray(points, float)
        if pts.shape[1] == 2:
            pts = np.c_[pts, np.zeros(len(pts))]
        s = pv.PolyData(pts).sample(m, tolerance=1e-9 * max(1.0, float(np.ptp(m.points, 0).max())))
        if not np.all(np.asarray(s.point_data["vtkValidPointMask"]) == 1):
            raise ValueError("some points lie outside the model")
        return np.asarray(s.point_data["_v"])

    def on_line(self, t: float, name: str, a, b, n: int = 101) -> tuple[np.ndarray, np.ndarray]:
        a, b = np.asarray(a, float), np.asarray(b, float)
        s = np.linspace(0.0, 1.0, n)
        pts = a[None, :] + s[:, None] * (b - a)[None, :]
        return s * np.linalg.norm(b - a), self.at_points(t, name, pts)

    def series(self, name: str, point) -> tuple[np.ndarray, np.ndarray]:
        vals = [self.at_points(t, name, np.atleast_2d(point))[0] for t in self.times]
        return self.times, np.array(vals)


@lru_cache(maxsize=64)
def _read(path: Path) -> pv.UnstructuredGrid:
    return pv.read(path)


def head(mesh: pv.UnstructuredGrid, model: Model) -> np.ndarray:
    """Hydraulic head h = p / (rho g) + elevation (elevation 0 without gravity)."""
    p = np.asarray(mesh.point_data["pressure_interpolated"] if "pressure_interpolated" in mesh.point_data
                   else mesh.point_data["pressure"])
    rho = model.physics.fluid.density
    ax = vertical_axis(model.geometry) if model.gravity_on else None
    z = mesh.points[:, {"y": 1, "z": 2}[ax]] if ax else 0.0
    return p / (rho * G) + z
