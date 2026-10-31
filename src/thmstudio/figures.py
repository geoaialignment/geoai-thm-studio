"""Result figures: field map, profile along a line, time series at a point."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .plotstyle import LINES, WIDTH, cmap_for, pyplot, wrap
from .post import Results
from .units import YEAR

UNITS = {"temperature": "K", "head": "m", "pressure": "Pa", "heat_flux": "W/m2", "darcy_velocity": "m/s"}


def _plt():
    return pyplot()


def _pt(p) -> str:
    return "(" + ", ".join(f"{float(v):.4g}" for v in p) + ") m"


def time_label(t: float) -> str:
    if t >= YEAR:
        return f"{t / YEAR:.3g} yr"
    if t >= 86400:
        return f"{t / 86400:.3g} d"
    if t >= 3600:
        return f"{t / 3600:.3g} h"
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
    v = np.asarray(tri.point_data["_v"])
    w, h = np.ptp(tri.points[:, xi]), np.ptp(tri.points[:, yi])
    equal = w > 0 and 0.2 < h / w < 5
    tall = equal and h / w > 1.2
    fig, ax = plt.subplots(figsize=(WIDTH, 5.4 if tall else 4.6))
    # quantities that cannot be negative start their scale at 0; small numerical undershoots show as the lightest colour
    lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
    nonneg = name not in ("temperature", "pressure", "head", "displacement", "sigma", "epsilon")
    if nonneg and lo < 0 < hi:
        lo = 0.0
    levels = np.linspace(lo, hi, 25) if hi > lo else 24
    cs = ax.tricontourf(T, v, levels=levels, cmap=cmap_for(name), extend="min" if nonneg and np.nanmin(v) < lo else "neither")
    if hi > lo:
        ax.tricontour(T, v, levels=np.linspace(lo, hi, 7)[1:-1], colors="white", linewidths=0.5, alpha=0.6)
    axisym = res.model is not None and res.model.geometry.kind in ("axisym_well", "axisym_source")
    ax.set_xlabel("r (m)" if axisym else "x (m)")
    ax.set_ylabel("z (m)" if (axisym or three_d) else "y (m)")
    if equal:
        ax.set_aspect("equal")
    cb = fig.colorbar(cs, ax=ax, location="right" if tall else "bottom", shrink=0.85, aspect=30, pad=0.02)
    cb.set_label(label)
    cb.outline.set_linewidth(0.5)
    cb.locator = __import__("matplotlib").ticker.MaxNLocator(6)
    cb.update_ticks()
    for s in ("top", "right"):
        ax.spines[s].set_visible(True)
    ax.set_title(wrap(title or f"{label}, t = {time_label(t)}"))
    fig.savefig(path)
    plt.close(fig)
    return path


def profile(res: Results, name: str, times: list[float], a, b, path: Path, n: int = 201,
            reference=None, n_values: int = 21) -> tuple[Path, dict]:
    """Plot with n samples; return n_values evenly spaced samples per time (keeps the answer short)."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(WIDTH, 4.4))
    data = {}
    label = name
    for i, t in enumerate(times):
        s, v = res.on_line(t, name, a, b, n)
        dv, label = _display(name, v)
        ax.plot(s, dv, color=LINES[i % len(LINES)], label=f"t = {time_label(t)}")
        k = np.linspace(0, len(s) - 1, n_values).round().astype(int)
        data[f"{t:g}"] = {"distance_m": s[k].round(6).tolist(), "value": v[k].tolist()}
        if reference is not None:
            ax.plot(s, _display(name, reference(s, t))[0], color="#1B262C", ls=(0, (4, 3)), lw=1.0,
                    label="exact solution" if i == 0 else None)
    ax.set_xlabel("distance along the line (m)")
    ax.set_ylabel(label)
    ax.grid(True)
    ax.margins(x=0)
    ncol = min(len(times) + (reference is not None), 4)
    fig.legend(loc="outside lower center", ncol=ncol, handlelength=2.2)
    ax.set_title(wrap(f"{label} from {_pt(a)} to {_pt(b)}"))
    fig.savefig(path)
    plt.close(fig)
    return path, data


def series(res: Results, name: str, point, path: Path) -> tuple[Path, dict]:
    plt = _plt()
    t, v = res.series(name, point)
    dv, label = _display(name, v)
    fig, ax = plt.subplots(figsize=(WIDTH, 4.0))
    scale, unit = (YEAR, "yr") if t.max() >= 2 * YEAR else (86400.0, "d") if t.max() >= 2 * 86400 else (1.0, "s")
    ax.plot(t / scale, dv, "-", color=LINES[0])
    ax.plot(t / scale, dv, "o", color=LINES[0], ms=4.5, mfc="white", mew=1.4)
    ax.set_xlabel(f"time ({unit})")
    ax.set_ylabel(label)
    ax.grid(True)
    ax.set_title(wrap(f"{label} at {_pt(point)}"))
    fig.savefig(path)
    plt.close(fig)
    return path, {"time_s": t.tolist(), "value": v.tolist()}
