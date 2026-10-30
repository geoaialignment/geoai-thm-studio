"""Figure 2: largest error of each verification case, grouped by configuration (verification_record.json)."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from thmstudio import configs  # noqa: E402

plt.rcParams.update({"font.family": "Helvetica", "font.size": 7.5})
rec = {r["id"]: r for r in json.loads((ROOT / "src/thmstudio/verification_record.json").read_text())}
cases = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in (ROOT / "src/thmstudio/cases").glob("*.json")}
FLOOR = 1e-4  # per cent; smaller errors are drawn here
rows = []
for cfg in configs.CONFIGURATIONS:
    ids = list(cfg.cases) + [i for i, c in cases.items() if c.get("kind") == "official" and c["configuration"] == cfg.id]
    for cid in ids:
        if cid in rec:
            worst = 100 * max(k["max_norm_error"] for k in rec[cid]["checks"])
            rows.append((cfg.id, cid, worst, cases[cid].get("kind") == "official"))
fig, ax = plt.subplots(figsize=(5.2, 5.6))
y = 0
ticks, labels, prev = [], [], None
for cfg, cid, w, off in rows:
    if prev and cfg != prev:
        y += 0.6
        ax.axhline(-y + 0.3, color="#D5DCDA", lw=0.6)
    v = max(w, FLOOR)
    ax.plot([FLOOR, v], [-y, -y], color="#9FB4B6", lw=1.0)
    ax.plot(v, -y, "o", ms=4.2, mfc="white" if off else "#21808B", mec="#21808B", mew=1.0)
    if w < FLOOR:
        exact = cases[cid].get("tolerance", {}).get("max_norm", 1) <= 1e-6
        ax.text(v * 1.35, -y, "< 0.0001 %" + (" (exact for the element)" if exact else ""), va="center",
                fontsize=6.3, color="#556")
    ticks.append(-y); labels.append(f"{cfg}  {cid}")
    prev = cfg
    y += 1
ax.axvline(1.0, color="#3E1F5A", lw=0.8, ls="--")
ax.text(1.08, -0.2, "1 %", color="#3E1F5A", fontsize=7)
ax.set_xscale("log"); ax.set_xlim(5e-5, 10)
ax.set_yticks(ticks); ax.set_yticklabels(labels, fontsize=6.6)
ax.set_ylim(-y + 0.4, 1.5)
ax.set_xlabel("largest error (%), normalized as stated in each case")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.plot([], [], "o", mfc="#21808B", mec="#21808B", label="model built from the model tree")
ax.plot([], [], "o", mfc="white", mec="#21808B", label="official OpenGeoSys input, unchanged")
ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, frameon=False, fontsize=6.6)
fig.savefig(ROOT / "docs/figures/Figure2_verification.png", dpi=300, bbox_inches="tight")
