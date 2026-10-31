"""Fill note_{en,ko}_template.md into GeoAI-THM-Studio_technical_note_{en,ko}.md (same numbers and tables as the preprint)."""
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bd", HERE.parent / "preprint" / "build_draft.py")
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)
# the note cites its own release (docs/technical_note/DOI); the preprint keeps the DOI of the release it describes
NOTE_DOI = (HERE / "DOI").read_text().strip() if (HERE / "DOI").exists() else None
for lang in ("en", "ko"):
    t = HERE / f"note_{lang}_template.md"
    if not t.exists():
        continue
    text = t.read_text()
    if lang == "ko":
        en = (HERE / "note_en_template.md").read_text()
        text = text.replace("{{TABLE1}}", bd.table1_ko()).replace("{{REFS}}", en[en.index("# References") + 13:].strip())
    if NOTE_DOI:
        text = text.replace("{{doi}}", NOTE_DOI)
    out = bd.fill(text)
    (HERE / f"GeoAI-THM-Studio_technical_note_{lang}.md").write_text(out)
    print(lang, "placeholders left:", sorted(set(re.findall(r"\{\{[^}]+\}\}", out))))
