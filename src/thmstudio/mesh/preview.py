"""Mesh pictures: regions in colour, named boundaries as labelled lines."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .contract import CORNERS, MeshBundle

REGION_COLOURS = ["#cfe3f2", "#f6dcc0", "#d9ead3", "#eadcf2", "#f9e79f", "#d5d8dc", "#f5cba7", "#c8e6c9"]
BASE_BOUNDARIES = {"left", "right", "bottom", "top", "well", "outer", "front", "back", "axis"}
INTERFACE_COLOURS = ["#3E1F5A", "#B03A2E", "#1B4F72", "#7D6608"]
LINE_COLOURS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#e377c2", "#17becf"]


def _polys(m):
    k = CORNERS[int(m.celltypes[0])]
    conn = m.cell_connectivity.reshape(m.n_cells, -1)[:, :k]
    return m.points[conn][:, :, :2]


def render_2d(bundle: MeshBundle, path: Path, zoom: tuple[float, float, float, float] | None = None,
              title: str = "", max_edges: int = 40_000) -> Path:
    from ..plotstyle import WIDTH, pyplot
    plt = pyplot()
    from matplotlib.collections import LineCollection, PolyCollection

    polys = _polys(bundle.bulk)
    mats = np.asarray(bundle.bulk.cell_data["MaterialIDs"])
    fig, ax = plt.subplots(figsize=(WIDTH, 4.8))
    face = [REGION_COLOURS[m % len(REGION_COLOURS)] for m in mats]
    show_edges = bundle.bulk.n_cells <= max_edges or zoom is not None
    ax.add_collection(PolyCollection(polys, facecolors=face, edgecolors="#444444" if show_edges else "none",
                                     linewidths=0.25))
    handles = []
    from matplotlib.patches import Patch
    for name, rid in bundle.regions.items():
        handles.append(Patch(facecolor=REGION_COLOURS[rid % len(REGION_COLOURS)], edgecolor="#444444",
                             label=f"region {name}"))
    main = [n for n in bundle.boundaries if n in BASE_BOUNDARIES]
    for i, name in enumerate(sorted(main)):
        m = bundle.boundaries[name]
        segs = m.points[m.cell_connectivity.reshape(m.n_cells, -1)[:, :2]][:, :, :2]
        lc = LineCollection(segs, colors=LINE_COLOURS[i % len(LINE_COLOURS)], linewidths=3.0, label=name,
                            zorder=4, capstyle="butt")
        ax.add_collection(lc)
        handles.append(lc)
    for name, m in bundle.interfaces.items():
        segs = m.points[m.cell_connectivity.reshape(m.n_cells, -1)[:, :2]][:, :, :2]
        lc = LineCollection(segs, colors=INTERFACE_COLOURS[len(handles) % len(INTERFACE_COLOURS)], linewidths=2.0,
                            linestyles=(0, (4, 2)), label=f"{name} (interface)", zorder=5)
        ax.add_collection(lc)
        handles.append(lc)
    lo, hi = bundle.bulk.points.min(0), bundle.bulk.points.max(0)
    pad = 0.03 * (hi - lo).max()
    if zoom:
        ax.set_xlim(zoom[0], zoom[1]); ax.set_ylim(zoom[2], zoom[3])
    else:
        ax.set_xlim(lo[0] - pad, hi[0] + pad); ax.set_ylim(lo[1] - pad, hi[1] + pad)
    ax.set_aspect("equal" if (hi - lo)[:2].max() / max((hi - lo)[:2].min(), 1e-30) < 30 else "auto")
    ax.set_xlabel("r (m)" if bundle.axisymmetric else "x (m)")
    ax.set_ylabel("z (m)" if bundle.axisymmetric else "y (m)")
    s = bundle.summary()
    ax.set_title(title or f"{s['elements']} {s['element_type']} elements, {s['nodes']} nodes ({s['engine']})")
    for side in ("top", "right"):
        ax.spines[side].set_visible(True)
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False, handlelength=1.6)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def render_3d(bundle: MeshBundle, path: Path, title: str = "") -> Path:
    import pyvista as pv
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True, window_size=(1000, 750))
    p.add_mesh(bundle.bulk, scalars="MaterialIDs", categories=True, show_edges=bundle.bulk.n_cells < 30_000,
               cmap=REGION_COLOURS[: max(1, len(bundle.regions))], show_scalar_bar=False, opacity=1.0)
    p.add_text(title or f"{bundle.bulk.n_cells} Hex8 elements, regions: {', '.join(bundle.regions)}", font_size=10)
    p.show_axes()
    p.camera_position = "iso"
    p.screenshot(str(path))
    p.close()
    return path


def render(bundle: MeshBundle, path: Path, zoom=None, title: str = "") -> Path:
    return render_3d(bundle, path, title) if bundle.dim == 3 else render_2d(bundle, path, zoom, title)
