"""Recompute (results/api_mesh_audit.json) each final-API card on the example's own mesh and report the difference (mesh influence)."""
import json, glob, sys
from pathlib import Path
from thmstudio.schema import Model, MeshSettings
from thmstudio.session import Session
from thmstudio.tools import call

rows = []
OUT = []
RUNS = "runs/final_api" if Path("runs/final_api").exists() else "scratch/final_api"  # runs/: published records
for proj in sorted(glob.glob(RUNS + "/*/*/*/")):
    P = Path(proj)
    if not (P / "cards.json").exists():
        continue
    audit = [json.loads(l) for l in (P / "audit.log").read_text().splitlines()]
    ex = next((json.loads(a["args"])["example_id"] for a in audit if a["tool"] == "start_from_example" and a["ok"]), None)
    card = json.loads((P / "cards.json").read_text())[-1]
    items = []
    for r in card["rows"]:
        agg = r["aggregation"]
        if agg == "largest difference":
            continue
        kind = {"change since start": "change"}.get(agg, agg)
        q = r["quantity"]; comp = None
        if "(" in q:
            q, comp = q.split(" (")[0], q.split("(")[1].rstrip(")")
        it = {"label": r["label"], "kind": kind, "field": q, "component": comp, "time": r["time"]}
        loc = r["location"]
        if loc.startswith("along "):
            it["probe"] = loc.split(" ")[1]
        elif loc != "whole model":
            nums = loc[loc.index("(") + 1:loc.index(")")]
            it["point"] = [float(x) for x in nums.split(",")]
        items.append(it)
    items = [items]
    if not ex or not items[0]:
        continue
    m = Model.model_validate_json((P / "model.json").read_text())
    exm = Model.model_validate(json.loads(Path(f"src/thmstudio/examples/{ex}.json").read_text())["model"])
    s = Session(root=Path("scratch/audit_final2") / P.parts[-3] / P.parts[-2])
    s.load_model(m.model_copy(update={"mesh": exm.mesh}))
    call(s, "build_mesh"); c = call(s, "check_model")
    if not c["ok"]:
        print(P.parts[-3], P.parts[-2], "reference check failed", [i["code"] for i in c["issues"] if i["level"] == "error"]); continue
    call(s, "run")
    while (st := call(s, "run_status")).get("status") not in ("succeeded", "failed"):
        pass
    its = [i for i in items[-1] if i.get("kind") != "comparison"]
    out = call(s, "answer_card", {"items": its})
    if not out["ok"]:
        print(P.parts[-3], P.parts[-2], "card failed", out.get("error")); continue
    ref = {r["label"]: r for r in s.cards[-1]["rows"]}
    for r in card["rows"]:
        if r["label"] in ref:
            a, b = float(r["value"]), float(ref[r["label"]]["value"])
            if r["aggregation"] == "change since start" and r["quantity"] in ("displacement", "stress"):
                a, b = abs(a), abs(b)  # cards before 0.1.0 final omitted the component on change rows; compare sizes
            OUT.append({"model": P.parts[-3], "scenario": P.parts[-2], "label": r["label"], "unit": r["unit"], "model_mesh": a, "example_mesh": b, "diff_pct": abs(a-b)/max(abs(b),1e-30)*100})
            print(f"{P.parts[-3]:14s} {P.parts[-2]:28s} {r['label'][:40]:40s} model mesh {a:10.4g}  example mesh {b:10.4g} {r['unit']:4s} diff {abs(a-b)/max(abs(b),1e-30)*100:6.1f} %", flush=True)

Path("results").mkdir(exist_ok=True)
json.dump(OUT, open("results/api_mesh_audit.json", "w"), indent=1, ensure_ascii=False)
