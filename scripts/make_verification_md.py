"""Write docs/VERIFICATION.md from the case files and the verification record."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from thmstudio import configs  # noqa: E402

record = {r["id"]: r for r in json.loads((ROOT / "src/thmstudio/verification_record.json").read_text())}
cases = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in sorted((ROOT / "src/thmstudio/cases").glob("*.json"))}


def pct(x):
    return f"{100 * x:.2g} %" if x >= 1e-4 else "< 0.01 %"


lines = ["# Verification", "",
         "Every configuration the agent computes is backed by the cases below. Each case builds its model from the same "
         "model tree the agent uses, runs OpenGeoSys 6.5.8, and compares the result with an exact solution or an "
         "official OpenGeoSys input. Errors are normalised as stated in each case file (`src/thmstudio/cases/`); "
         "tolerances were fixed before the comparison and checked by halving element size and time step together. "
         "Each result is recorded with the package and OpenGeoSys versions it was computed with; the agent computes a "
         "configuration only when all its cases have passed with the installed versions (here 0.1.0 and 6.5.8).", ""]
for cfg in configs.CONFIGURATIONS:
    lines += [f"## {cfg.id}: {cfg.title}", "", "| case | what is compared | source | tolerance | largest error | result |",
              "|---|---|---|---|---|---|"]
    ids = list(cfg.cases) + [i for i, c in cases.items() if c.get("kind") == "official" and c["configuration"] == cfg.id]
    for cid in ids:
        c, r = cases.get(cid), record.get(cid)
        if c is None:
            continue
        tol = c.get("tolerance", {})
        tol_s = ", ".join(f"{k.replace('_', ' ')} {pct(v) if v < 1 else v}" for k, v in tol.items()) or "-"
        if not c.get("observations"):
            parts = [f"heat stored = power x time within {pct(i['tolerance'])}" for i in c.get("integrals", [])][:1]
            parts += [f"change between element size 2h and h at {cv['field']} points within {pct(cv['max_rel_change'])}"
                      for cv in c.get("convergence", [])]
            tol_s = "; ".join(parts) + "; region areas checked against the geometry when the mesh is built"
        extra = [f"{o.get('label', '')}: " + ", ".join(f"{k.replace('_', ' ')} {pct(v)}" for k, v in o["tolerance"].items())
                 for o in c.get("observations", []) if o.get("tolerance") and o["tolerance"] != tol]
        if extra and len(extra) <= 2:
            tol_s += "; " + "; ".join(extra)
        elif extra:
            tol_s += "; other tolerances for some checks (see the case file)"
        if r is None:
            res, worst = "not run", "-"
        else:
            worst = pct(max((k["max_norm_error"] for k in r["checks"]), default=float("nan")))
            if not c.get("observations"):
                worst += " (largest check value)"
            res = "passed" if r["passed"] else "FAILED"
        lines.append(f"| {cid} | {c['title']} | {c.get("source", "official OpenGeoSys input " + c.get("official", ""))} | {tol_s} | {worst} | {res} |")
    notes = [(cid, cases[cid]["note"]) for cid in ids if cid in cases and cases[cid].get("note")]
    if notes:
        lines.append("")
        lines += [f"- {cid}: {n}" for cid, n in notes]
    if cfg.demonstration:
        lines += ["", "This configuration is a demonstration: no exact solution exists, so it is checked for energy "
                  "balance, mesh and time-step convergence, region areas, and a homogeneous limit equal to THM-AX."]
    lines.append("")
lines += ["Run `thmstudio verify` to repeat all cases on your machine; the agent reports your results instead of the "
          "release record once they exist.", ""]
(ROOT / "docs" / "VERIFICATION.md").write_text("\n".join(lines))
print("\n".join(lines[:12]))
