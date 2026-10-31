#!/bin/bash
# Build the release PDFs: technical notes (EN, KO) and the preprint. Markdown -> DOCX (pandoc) -> formatting
# (python-docx) -> PDF (LibreOffice). Run after technical_note/build_note.py and preprint/build_draft.py.
set -e
cd "$(dirname "$0")"
PY=python3  # needs python-docx
SOFFICE=/Applications/LibreOffice.app/Contents/MacOS/soffice
VERSION=0.1.1  # technical notes; the preprint stays the v0.1.0 text submitted to ESSOAr
cd technical_note
for L in en ko; do
  OUT=GeoAI-THM-Studio-v${VERSION}_technical_note_$L
  pandoc GeoAI-THM-Studio_technical_note_$L.md -o $OUT.docx --resource-path=.:..
  $PY - "$OUT.docx" "$L" <<'PYEOF'
import sys
import docx
from docx.oxml.ns import qn
from docx.shared import Pt, Inches
path, lang = sys.argv[1], sys.argv[2]
EA = "AppleMyungjo" if lang == "ko" else "Times New Roman"
d = docx.Document(path)
for s in d.sections:
    s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Inches(1)
for st in d.styles:
    try:
        st.font.name = "Times New Roman"
        rf = st.element.get_or_add_rPr().find(qn("w:rFonts"))
        if rf is not None:
            for a in ("w:hAnsi", "w:ascii", "w:cs"):
                rf.set(qn(a), "Times New Roman")
            rf.set(qn("w:eastAsia"), EA)
        st.font.color.rgb = None
    except Exception:
        pass
d.styles["Normal"].font.size = Pt(11)
for name, size in (("Title", 17), ("Subtitle", 12), ("Heading 1", 13), ("Heading 2", 11.5), ("Body Text", 11),
                   ("First Paragraph", 11), ("Compact", 10), ("Image Caption", 10)):
    if name in [s.name for s in d.styles]:
        d.styles[name].font.size = Pt(size)
for p in d.paragraphs:
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.2 if lang == "ko" else 1.15
    for r in p.runs:
        r.font.color.rgb = None
        r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), EA)
for t in d.tables:
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
                    r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), EA)
for shape in d.inline_shapes:
    ratio = shape.height / shape.width
    shape.width = Inches(6.5)
    shape.height = int(Inches(6.5) * ratio)
d.save(path)
PYEOF
  $SOFFICE --headless --convert-to pdf $OUT.docx >/dev/null 2>&1
done
ls -la *.pdf
[ "$1" = "--with-preprint" ] || exit 0
cd ../preprint
pandoc draft.md -o GeoAI-THM-Studio_preprint.docx --resource-path=.:..
$PY ~/.claude/skills/paper-writing/scripts/format_docx.py GeoAI-THM-Studio_preprint.docx --lines
$SOFFICE --headless --convert-to pdf GeoAI-THM-Studio_preprint.docx >/dev/null 2>&1
ls -la ../technical_note/*.pdf GeoAI-THM-Studio_preprint.pdf
