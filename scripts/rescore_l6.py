"""Rescore the recorded L6 stand-in runs (scratch/l6) with the released judge and guardrail; write results/l6_rescored.json."""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "tests/l6")
from run_l6 import judge  # noqa: E402

RUNS = Path("runs/l6") if Path("runs/l6").exists() else Path("scratch/l6")  # runs/: the published run records
sc = {x["id"]: x for x in json.load(open("tests/l6/scenarios.json"))}
rs = json.load(open(RUNS / "results_haiku.json"))
rs = rs if isinstance(rs, list) else rs["results"]
out = []
for r in rs:
    proj = glob.glob(str(RUNS / r["id"] / "projects" / "*"))
    audit = [json.loads(line) for p in proj for line in open(p + "/audit.log")]
    j = judge(sc[r["id"]], {"final": r["final"], "audit": audit, "projects": proj, "seconds": r.get("seconds", 0),
                            "turns": 0, "cost_usd": 0})
    out.append({"id": r["id"], "passed": j["passed"], "checks": j["checks"], "unsupported_numbers": j["unsupported_numbers"],
                "calls": r.get("calls"), "errors": r.get("errors"), "seconds": r.get("seconds")})
Path("results").mkdir(exist_ok=True)
json.dump(out, open("results/l6_rescored.json", "w"), indent=1, ensure_ascii=False)
print(sum(o["passed"] for o in out), "of", len(out), [o["id"] for o in out if not o["passed"]])
