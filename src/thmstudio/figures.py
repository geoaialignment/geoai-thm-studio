"""Result figures: field map, profile along a line, time series at a point."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .post import Results
from .units import YEAR

UNITS = {"temperature": "K", "head": "m", "pressure": "Pa", "heat_flux": "W/m2", "darcy_velocity": "m/s"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _pt(p) -> str:
    return "(" + ", ".join(f"{float(v):.4g}" for v in p) + ") m"


def time_label(t: float) -> str:
    if t >= YEAR:
        return f"{t / YEAR:.3g} yr"
    if t >= 86400:
        return f"{t / 86400:.3g} d"
    return f"{t:.3g} s"


def _display(name: str, v: np.ndarray) -> tuple[np.ndarray, str]:
    if name == "temperature":
        return v - 273.15, "temperature (°C)"
    if name == "pressure":
        return v / 1e6, "pressure (MPa)"
    if v.ndim == 2:
        return np.linalg.norm(v, axis=1), f"|{name}| ({UNITS.get(name, '')})"
    return v, f"{name} ({UNITS.get(name, '-')})"


def field_map(res: Results, name: str, t: float, path: Path, title: str = "") -> Path:
    """Filled contours of a field; 3D models are shown on the vertical slice through the centre."""
    plt = _plt()
    import matplotlib.tri as mtri
    m = res.mesh_at(t).copy()
    vals, label = _display(name, res.field(m, name))
    m.point_data["_v"] = vals
    three_d = np.ptp(m.points[:, 2]) > 0
    if three_d:
        c = m.center
        m = m.slice(normal="y", origin=c)
        title = title or f"{label} on the slice y = {c[1]:.3g} m, t = {time_label(t)}"
    tri = m.triangulate()
    faces = (tri.faces.reshape(-1, 4) if three_d else tri.cells.reshape(-1, 4))[:, 1:]
    xi, yi = (0, 2) if three_d else (0, 1)
    T = mtri.Triangulation(tri.points[:, xi], tri.points[:, yi], faces)
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    cs = ax.tricontourf(T, np.asarray(tri.point_data["_v"]), levels=20, cmap="viridis")
    axisym = res.model is not None and res.model.geometry.kind == "axisym_well"
    ax.set_xlabel("r (m)" if axisym else "x (m)")
    ax.set_ylabel("z (m)" if (axisym or three_d) else "y (m)")
    fig.colorbar(cs, ax=ax, label=label)
    w, h = np.ptp(tri.points[:, xi]), np.ptp(tri.points[:, yi])
    if w > 0 and 0.05 < h / w < 20:
        ax.set_aspect("equal")
    ax.set_title(title or f"{label}, t = {time_label(t)}", fontsize=10)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def profile(res: Results, name: str, times: list[float], a, b, path: Path, n: int = 201,
            reference=None, n_values: int = 21) -> tuple[Path, dict]:
    """Plot with n samples; return n_values evenly spaced samples per time (keeps the answer short)."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
    data = {}
    label = name
    for t in times:
        s, v = res.on_line(t, name, a, b, n)
        dv, label = _display(name, v)
        ax.plot(s, dv, label=f"t = {time_label(t)}")
        k = np.linspace(0, len(s) - 1, n_values).round().astype(int)
        data[f"{t:g}"] = {"distance_m": s[k].round(6).tolist(), "value": v[k].tolist()}
        if reference is not None:
            ax.plot(s, _display(name, reference(s, t))[0], "k--", lw=0.8)
    ax.set_xlabel("distance along the line (m)")
    ax.set_ylabel(label)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    ax.set_title(f"{label} from {_pt(a)} to {_pt(b)}", fontsize=10)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path, data


def series(res: Results, name: str, point, path: Path) -> tuple[Path, dict]:
    plt = _plt()
    t, v = res.series(name, point)
    dv, label = _display(name, v)
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
    scale, unit = (YEAR, "yr") if t.max() >= 2 * YEAR else (86400.0, "d") if t.max() >= 2 * 86400 else (1.0, "s")
    ax.plot(t / scale, dv, "o-", ms=3)
    ax.set_xlabel(f"time ({unit})")
    ax.set_ylabel(label)
    ax.grid(alpha=0.3)
    ax.set_title(f"{label} at {_pt(point)}", fontsize=10)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path, {"time_s": t.tolist(), "value": v.tolist()}
