"""Technical-note figure (v0.1.1): the mesh gpt-6.1-terra built from a plain-language request (recorded conversation
of 2026-10-31, tests/final_api/nl_mesh_ledger.json). Left: the whole axisymmetric model; right: the canister and
buffer. Reads the mesh files the agent's build_mesh call wrote to scratch/nl_mesh/ (copied to runs/nl_mesh/).
Run from the project root: env/venv-lean/bin/python docs/figures/src/fig_nl_mesh.py
"""
from pathlib import Path

import numpy as np
import pyvista as pv
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.patches import Patch

from thmstudio.mesh.contract import CORNERS
from thmstudio.plotstyle import INK, pyplot

ROOT = Path(__file__).resolve().parents[3]
B = ROOT / "runs/nl_mesh/repository_canister/build"
OUT = ROOT / "docs/figures/FigureN_nl_mesh.png"
COLOURS = {0: "#D4E3EE", 1: "#F2CFA6", 2: "#D9E6C8"}       # rock, canister, buffer (MaterialIDs of the mesh)
NAMES = {0: "granite", 1: "canister", 2: "bentonite buffer"}
IFACE = {"canister_surface": "#8C4A1E", "buffer_rock": "#3E3F83"}


def polys(m):
    k = CORNERS[int(m.celltypes[0])]
    conn = m.cell_connectivity.reshape(m.n_cells, -1)[:, :k]
    return m.points[conn][:, :, :2]


def segments(m):
    return m.points[m.cell_connectivity.reshape(m.n_cells, -1)[:, :2]][:, :, :2]


plt = pyplot()
m = pv.read(B / "mesh.vtu")
P = polys(m)
mats = np.asarray(m.cell_data["MaterialIDs"])
fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.9), gridspec_kw={"width_ratios": [1.0, 0.62]})
for ax, (xl, yl), lw in ((axes[0], ((0, 50), (0, 50)), 0.15), (axes[1], ((0, 1.6), (0, 3.6)), 0.35)):
    ax.add_collection(PolyCollection(P, facecolors=[COLOURS[int(i)] for i in mats], edgecolors="#4A5258",
                                     linewidths=lw))
    for name, col in IFACE.items():
        f = B / f"mesh_interface_{name}.vtu"
        if f.exists():
            ax.add_collection(LineCollection(segments(pv.read(f)), colors=col, linewidths=1.6, zorder=3))
    ax.set_xlim(*xl); ax.set_ylim(*yl); ax.set_aspect("equal")
    ax.set_xlabel("r (m)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(True)
axes[0].set_ylabel("z (m)")
axes[0].set_title(f"whole model, {m.n_cells:,} elements")
axes[1].set_title("canister and buffer")
axes[0].add_patch(plt.Rectangle((0, 0), 1.6, 3.6, fill=False, ec=INK, lw=1.0, zorder=4))
handles = [Patch(facecolor=COLOURS[i], edgecolor="#4A5258", label=NAMES[i]) for i in (1, 2, 0)]
fig.legend(handles=handles, loc="outside lower center", ncol=3)
fig.savefig(OUT)
print("written", OUT, m.n_cells, "elements")
