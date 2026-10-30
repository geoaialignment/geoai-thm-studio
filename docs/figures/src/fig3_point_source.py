"""Figure 3: pore-pressure rise 0.5 m from the 300 W point source at 50000 s against the smallest element size at the
source, the sweep on the example (results/point_source_sweep.json) and the answers of the language models
(tests/final_api/ledger.json)."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
plt.rcParams.update({"font.family": "Helvetica", "font.size": 7.5})
S = json.loads((ROOT / "results/point_source_sweep.json").read_text())
ell, exact = S["ell_m"], S["exact_MPa"]
rows = sorted([r for r in S["rows"] if not r.get("study") and "pressure_MPa" in r], key=lambda r: r["h"])
# answers: (h, pressure MPa, label, marker); h is the smallest element at the source the model chose
ANS = [(0.2, -0.507, "gpt-6-luna, no rule\n(far field 1 m)", "v"),
       (0.1, 0.635, "gpt-6.1-terra, no rule", "v"),
       (0.05, 0.998, "gpt-6-luna, rule $\\ell$/2\n(100 × 100 elements)", "s"),
       (0.05, 0.887, "gpt-6.1-terra, rule $\\ell$/2", "s"),
       (0.0145, 0.971, "gpt-6.1-terra, rule $\\ell$/4\n(took $\\ell$/8, far field 0.2 m)", "D")]
fig, ax = plt.subplots(figsize=(5.0, 3.3))
ax.axhline(exact, color="#3E1F5A", lw=0.9, ls="--")
ax.text(0.38, exact - 0.06, f"exact solution {exact:.3f} MPa", color="#3E1F5A", fontsize=7, ha="right")
ax.plot([r["h"] for r in rows], [r["pressure_MPa"] for r in rows], "-o", color="#21808B", ms=3.5, lw=1.0,
        label="example, only the source element size changed")
for h, p, lab, mk in ANS:
    ax.plot(h, p, mk, ms=6, mfc="white", mec="#1B262C", mew=1.0)
    dx, dy, ha = {"v": (1.08, 0.0, "left"), "s": (1.1, 0.0, "left"), "D": (0.97, -0.17, "left")}[mk]
    off = {0.998: 0.08, 0.887: -0.09}.get(p, 0.0)
    ax.text(h * dx, p + dy + off, lab, fontsize=6.3, ha=ha, va="center")
for frac, lab in ((0.5, r"$\ell$/2"), (0.25, r"$\ell$/4"), (0.125, r"$\ell$/8")):
    ax.axvline(frac * ell, color="#9FB4B6", lw=0.8, ls=":")
    ax.text(frac * ell, -0.62, lab, ha="center", va="bottom", fontsize=7, color="#556")
ax.set_xscale("log")
ax.set_xlim(0.004, 0.4)
ax.set_ylim(-0.65, 1.2)
ax.set_xlabel("element size requested at the source, h (m)")
ax.set_ylabel("pore-pressure rise at 0.5 m, 50,000 s (MPa)")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.plot([], [], "v", mfc="white", mec="#1B262C", label="answer of a language model")
ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), frameon=False, fontsize=6.6, ncol=2)
fig.savefig(ROOT / "docs/figures/Figure3_point_source.png", dpi=300, bbox_inches="tight")
