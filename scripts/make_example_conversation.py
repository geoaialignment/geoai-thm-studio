"""Write docs/EXAMPLE_CONVERSATION.md from recorded runs: the request, the tool calls and the final answer, unedited.

Usage: python scripts/make_example_conversation.py <run root> <model>/<scenario id> [...]
<run root> holds one folder per model with one folder per scenario (scratch/final_api).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
run_root, ids = Path(sys.argv[1]), sys.argv[2:]
scen = {s["id"]: s for s in json.loads((ROOT / "tests/l6/scenarios.json").read_text())}
ledger = ROOT / "tests/final_api/ledger.json"
finals = {(r["model"], r["id"]): r for r in json.loads(ledger.read_text()) if r.get("passed") is not None} \
    if ledger.exists() else {}

out = ["# Example conversations\n\nRecorded in the final check with the OpenAI API. The answers are printed as the model "
       "wrote them, except that local paths are shortened. The tool list is taken from the audit log of each project.\n"]
for key in ids:
    model, sid = key.split("/")
    final = finals.get((model, sid), {}).get("final", "")
    audits = []
    for f in sorted((run_root / model / sid).glob("**/audit.log")):
        audits += [json.loads(l) for l in f.read_text().splitlines()]
    audits.sort(key=lambda a: a["time"])
    out.append(f"## {sid} ({model})\n\n**Request**\n\n> {scen[sid]['request']}\n\n**Tool calls**\n")
    for a in audits:
        args = re.sub(r"/(?:Users|home)/\S*?/([^/\s\"]+)(?=[\s\"]|$)", r"\1", a["args"])
        args = args if len(args) <= 160 else args[:157] + "..."
        out.append(f"- `{a['tool']}` {'' if a['ok'] else '(returned an error) '}{args if args != '{}' else ''}")
    final = re.sub(r"/(?:Users|home)/[^\s`)]*?/([^/\s`)]+/[^/\s`)]+)(?=[\s`)]|$)", r"~/thmstudio_projects/\1", final)
    out.append(f"\n**Answer**\n\n{final}\n")
text = "\n".join(out)
assert "/Users/" not in text
(ROOT / "docs/EXAMPLE_CONVERSATION.md").write_text(text)
print("written", len(ids), "conversations")
