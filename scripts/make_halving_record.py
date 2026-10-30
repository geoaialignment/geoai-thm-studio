"""Summarise the refinement run (thmstudio verify --refine, element size and time step halved) into
results/verification_halving.json: the largest normalized error of each transient case at h and at h/2."""
import json
import sys
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else "scratch/verify_refine_final/results.json")
rows, skipped = [], []
for r in json.loads(src.read_text()):
    ref = r.get("refined") or {}
    if not ref.get("checks"):
        skipped.append({"id": r["id"], "reason": "the refined run did not finish within the run-time limit"})
        continue
    a = max(c["max_norm_error"] for c in r["checks"])
    b = max(c["max_norm_error"] for c in ref["checks"])
    case = json.loads(Path(f"src/thmstudio/cases/{r['id']}.json").read_text())
    rows.append({"id": r["id"], "steady": case["model"]["study"].get("kind") == "steady", "error_h": a, "error_h2": b, "ratio": b / a,
                 "package_version": r.get("package_version"), "ogs_version": r.get("ogs_version")})
out = {"note": "largest normalized max-norm error per case at the released discretization (h) and with element size "
               "and time step halved (h/2)", "cases": rows, "skipped": skipped}
Path("results/verification_halving.json").write_text(json.dumps(out, indent=1))
print(len(rows), "cases;", "ratios", sorted(round(r["ratio"], 2) for r in rows), "skipped", [s["id"] for s in skipped])
