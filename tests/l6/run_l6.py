"""L6: a small Claude model drives the tools through the MCP server (no OpenAI API).

Each scenario gives a user request; the model sees only our system prompt, rules, policies and skills,
and the THM Studio tools. Results are judged from the project folder (audit log, cards), not from the
model's own claims. Failure causes: model / harness / engine / time.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "src" / "thmstudio" / "agent"
PY = ROOT / "env" / "venv-lean" / "bin" / "python"


def system_prompt() -> str:
    parts = [(AGENT / "instructions" / f).read_text() for f in ("system_prompt.md", "rules.md", "policies.md")]
    parts += [(AGENT / "skills" / f"{s}.md").read_text() for s in ("geometry", "physics", "materials", "conditions",
                                                                  "mesh", "study", "results")]
    parts.append("Tool calls that do not fit the current state return the state and the next step; follow it. "
                 "Run long computations by calling run, then run_status until it reports succeeded or failed.")
    return "\n\n".join(parts)


def run_scenario(sc: dict, out: Path, model: str = "haiku", timeout: float = 1500) -> dict:
    proj = out / "projects"
    shutil.rmtree(out, ignore_errors=True)
    proj.mkdir(parents=True)
    cfg = out / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"thm": {"command": str(PY), "args": ["-m", "thmstudio.mcp_server", str(proj)]}}}))
    cmd = ["claude", "-p", sc["request"], "--model", model, "--system-prompt", system_prompt(),
           "--mcp-config", str(cfg), "--strict-mcp-config", "--tools", "", "--allowedTools", "mcp__thm__*",
           "--settings", json.dumps({"disableAllHooks": True}),
           "--output-format", "json", "--max-turns", str(sc.get("max_turns", 80))]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=out)
        raw = p.stdout
    except subprocess.TimeoutExpired:
        raw = ""
    secs = time.time() - t0
    (out / "claude.json").write_text(raw)
    try:
        res = json.loads(raw)
    except ValueError:
        res = {"result": raw[-2000:], "is_error": True}
    audits = []
    for f in proj.glob("*/audit.log"):
        audits += [json.loads(l) for l in f.read_text().splitlines()]
    return {"id": sc["id"], "seconds": round(secs, 1), "final": res.get("result", ""), "turns": res.get("num_turns"),
            "cost_usd": res.get("total_cost_usd"), "audit": audits, "projects": [str(p) for p in proj.iterdir()],
            "session_id": res.get("session_id"), "cmd": cmd, "cfg": str(cfg)}


def guardrail_retry(r: dict, bad: list[str], out: Path, model: str) -> str:
    """Emulate the SDK output guardrail: resume the same session once with its message."""
    msg = (f"Your answer quoted numbers that are not on the answer card, in my inputs or in a tool result: "
           f"{', '.join(bad)}. Rewrite the answer using only those numbers (no differences, ratios, conversions or "
           f"suggested values of your own).")
    cmd = ["claude", "-p", msg, "--resume", r["session_id"], "--model", model, "--system-prompt", system_prompt(),
           "--mcp-config", r["cfg"], "--strict-mcp-config", "--tools", "", "--allowedTools", "mcp__thm__*",
           "--settings", json.dumps({"disableAllHooks": True}), "--output-format", "json", "--max-turns", "10"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=out)
        return json.loads(p.stdout).get("result", "")
    except (subprocess.TimeoutExpired, ValueError):
        return ""


def judge(sc: dict, r: dict) -> dict:
    tools = [a["tool"] for a in r["audit"]]
    ok_tools = [a["tool"] for a in r["audit"] if a["ok"]]
    errors = [a for a in r["audit"] if not a["ok"]]
    expect = sc["expect"]
    checks = {}
    if expect.get("computed"):
        checks["ran"] = "run" in ok_tools
        checks["card"] = "answer_card" in ok_tools
    if expect.get("refused"):
        checks["no_run"] = "run" not in ok_tools
        checks["contact"] = "geoaialign" in r["final"].lower() or "geoai alignment" in r["final"].lower()
    if expect.get("example"):
        checks["example"] = any(a["tool"] == "start_from_example" and a["ok"] and expect["example"] in a["args"]
                                for a in r["audit"])
    for name in expect.get("tools", []):
        checks[f"used_{name}"] = name in ok_tools
    if "min_runs" in expect:
        checks["runs"] = sum(1 for a in r["audit"] if a["tool"] == "run" and a["ok"]) >= expect["min_runs"]
    if "explains" in expect:
        checks["explains_limit"] = any(k.lower() in r["final"].lower() for k in expect["explains"])
    if "forbidden" in expect:  # no successful run of the forbidden setting (read from the saved model)
        bad_run = False
        for pdir in r["projects"]:
            mj = Path(pdir) / "model.json"
            ran = any(a["tool"] == "run" and a["ok"] for a in r["audit"])
            if mj.exists() and ran:
                m = json.loads(mj.read_text())
                f = expect["forbidden"]
                if f == "gravity_mechanics" and m["physics"]["process"] in ("HM", "TM", "THM") and m["physics"].get("gravity"):
                    bad_run = True
                if f == "steady_transport" and m["physics"]["process"] == "HC" and m["study"]["kind"] == "steady":
                    bad_run = True
        checks["no_forbidden_run"] = not bad_run
    # numbers in the final answer must come from the card or the inputs (same rule as the SDK guardrail)
    sys.path.insert(0, str(ROOT / "src"))
    from thmstudio.report import check_answer
    from thmstudio.schema import Model
    unsupported = []
    for pdir in r["projects"]:
        mj, cj, sj = Path(pdir) / "model.json", Path(pdir) / "cards.json", Path(pdir) / "seen_numbers.json"
        if mj.exists() and cj.exists():
            seen = json.loads(sj.read_text()) if sj.exists() else []
            unsupported = check_answer(r["final"], Model.model_validate_json(mj.read_text()), json.loads(cj.read_text()), seen,
                                       user_text=sc["request"])
    if expect.get("computed"):
        checks["numbers_from_card"] = not unsupported
    passed = all(checks.values()) if checks else False
    cause = None
    if not passed:
        if not tools:
            cause = "model"
        elif any(a["tool"] == "run_status" and "failed" in a.get("note", "") for a in r["audit"]):
            cause = "engine"
        else:
            cause = "model"
    return {"id": sc["id"], "passed": passed, "checks": checks, "unsupported_numbers": unsupported[:10],
            "calls": len(tools), "errors": len(errors),
            "error_tools": sorted({a["tool"] for a in errors}), "cause": cause, "seconds": r["seconds"],
            "turns": r["turns"], "cost_usd": r["cost_usd"]}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--out", default=str(ROOT / "scratch" / "l6"))
    a = ap.parse_args(argv)
    scenarios = json.loads((Path(__file__).parent / "scenarios.json").read_text())
    rows = []
    for sc in scenarios:
        if a.ids and sc["id"] not in a.ids:
            continue
        r = run_scenario(sc, Path(a.out) / sc["id"], a.model)
        j = judge(sc, r)
        if j.get("unsupported_numbers") and r.get("session_id"):
            j["first_attempt"] = {"passed": j["passed"], "unsupported_numbers": j["unsupported_numbers"]}
            r["final"] = guardrail_retry(r, j["unsupported_numbers"], Path(a.out) / sc["id"], a.model)
            j = {**judge(sc, r), "first_attempt": j["first_attempt"], "guardrail_retry": True}
        rows.append({**j, "final": r["final"][:1500]})
        print(json.dumps(j, ensure_ascii=False), flush=True)
    (Path(a.out) / f"results_{a.model}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
