"""Technical-note figure: salt concentration in the Elder problem at 1, 2 and 4 years, this harness (case E2) and the
official OpenGeoSys benchmark output on the same grid. Reads scratch/verify_final/E2 (rerun `thmstudio verify E2`)."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv

ROOT = Path(__file__).resolve().parents[3]
plt.rcParams.update({"font.family": "Helvetica", "font.size": 7.5})
OURS = ROOT / "scratch/verify_final/E2/run"
OFF = ROOT / "references/ogs-6.5.8/Parabolic/ComponentTransport/elder"
times = [(120, 31557600, "1 year"), (240, 63115200, "2 years"), (480, 126230400, "4 years")]
x = np.linspace(0.5, 299.5, 300); y = np.linspace(0.5, 149.5, 150)
X, Y = np.meshgrid(x, y)


def grid(mesh, field, pts):
    s = pv.PolyData(pts).sample(mesh)
    return np.asarray(s.point_data[field]).reshape(X.shape)


fig, axes = plt.subplots(2, 3, figsize=(7.0, 2.6), sharex=True, sharey=True)
for j, (ts, t, lab) in enumerate(times):
    ours = pv.read(OURS / f"e2_ts_{ts}_t_{t}.000000.vtu")
    off = pv.read(OFF / f"elder_ts_{ts}_t_{t}.000000_reference.vtu")
    a = grid(ours, "salt", np.c_[X.ravel(), Y.ravel(), np.zeros(X.size)])
    b = grid(off, "Si", np.c_[X.ravel() - 150, np.zeros(X.size), Y.ravel() - 75])
    for i, f in enumerate((a, b)):
        ax = axes[i, j]
        im = ax.imshow(f, origin="lower", extent=(0, 300, 0, 150), cmap="viridis", vmin=0, vmax=1, aspect="equal")
        ax.contour(X, Y, f, levels=[0.2, 0.6], colors="white", linewidths=0.5)
        if i == 0:
            ax.set_title(lab, fontsize=8)
    print(lab, "largest point difference", float(np.nanmax(np.abs(a - b))), "min ours", float(np.nanmin(a)))
axes[0, 0].set_ylabel("this harness\nz (m)")
axes[1, 0].set_ylabel("official benchmark\nz (m)")
for ax in axes[1]:
    ax.set_xlabel("x (m)")
cb = fig.colorbar(im, ax=axes, shrink=0.85, pad=0.015, extend="min")
cb.set_label("salt concentration / source concentration")
fig.savefig(ROOT / "docs/figures/FigureN_elder.png", dpi=300, bbox_inches="tight")
