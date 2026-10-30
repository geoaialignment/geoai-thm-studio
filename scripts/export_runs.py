"""Copy the records of the stand-in and API runs that the result scripts need into runs/, without local paths."""
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = ("model.json", "cards.json", "seen_numbers.json", "audit.log")
HOME = str(Path.home())


def clean(text: str) -> str:
    text = text.replace(str(ROOT) + "/", "").replace(str(ROOT), ".")
    text = text.replace("file://" + HOME, "file://~").replace(HOME, "~")
    return re.sub(r"/private/tmp/[^\s\"']*", "<tmp>", text)


def copy_tree(src: Path, dst: Path):
    for f in src.rglob("*"):
        if f.is_file() and f.name in KEEP and "build" not in f.parts and "runs" not in f.relative_to(src).parts:
            out = dst / f.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(clean(f.read_text()))


out = ROOT / "runs"
shutil.rmtree(out, ignore_errors=True)
copy_tree(ROOT / "scratch/l6", out / "l6")
(out / "l6" / "results_haiku.json").write_text(clean((ROOT / "scratch/l6/results_haiku.json").read_text()))
copy_tree(ROOT / "scratch/final_api", out / "final_api")
led = ROOT / "tests/final_api/ledger.json"
led.write_text(clean(led.read_text()))
n = sum(1 for _ in out.rglob("*") if _.is_file())
left = [str(p) for p in out.rglob("*") if p.is_file() and (HOME in p.read_text() or "/Users/" in p.read_text())]
print(n, "files; with local paths:", left[:5])
