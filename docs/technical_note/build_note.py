"""Fill note_{en,ko}_template.md into GeoAI-THM-Studio_technical_note_{en,ko}.md (same numbers and tables as the preprint)."""
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bd", HERE.parent / "preprint" / "build_draft.py")
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)
for lang in ("en", "ko"):
    t = HERE / f"note_{lang}_template.md"
    if not t.exists():
        continue
    text = t.read_text()
    if lang == "ko":
        en = (HERE / "note_en_template.md").read_text()
        text = text.replace("{{TABLE1}}", bd.table1_ko()).replace("{{REFS}}", en[en.index("# References") + 13:].strip())
    out = bd.fill(text)
    (HERE / f"GeoAI-THM-Studio_technical_note_{lang}.md").write_text(out)
    print(lang, "placeholders left:", sorted(set(re.findall(r"\{\{[^}]+\}\}", out))))
