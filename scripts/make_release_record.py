"""Copy verification/results.json into the package as the release record, without machine-specific paths."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
records = json.loads((ROOT / "verification" / "results.json").read_text())
for r in records:
    (r.get("run") or {}).pop("rundir", None)
text = json.dumps(records, indent=1, ensure_ascii=False)
assert str(Path.home()) not in text
(ROOT / "src" / "thmstudio" / "verification_record.json").write_text(text + "\n")
print(len(records), "cases written to the release record")
