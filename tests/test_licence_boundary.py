"""gmsh (GPL) must run only as a separate program: no module of the package may import it."""
import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "thmstudio"


def test_no_gmsh_import_in_source():
    found = []
    for f in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            found += [f"{f.name}:{node.lineno}" for n in names if n.split(".")[0] == "gmsh"]
        assert "__import__(\"gmsh\")" not in f.read_text() and "import_module(\"gmsh\")" not in f.read_text()
    assert not found, found


def test_gmsh_mesh_build_leaves_gmsh_unimported(tmp_path):
    code = f"""
import sys
from pathlib import Path
from thmstudio.session import Session
from thmstudio.tools import call
s = Session(root=Path({str(tmp_path)!r}))
call(s, "start_from_example", {{"example_id": "heated_inclusion"}})
b = call(s, "build_mesh")
print(b.get("engine"), "gmsh" in sys.modules)
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    engine, imported = out.stdout.split()[-2:]
    assert engine == "gmsh" and imported == "False", out.stdout


def test_missing_linux_library_gives_install_command(tmp_path, monkeypatch):
    import pytest
    from thmstudio.mesh import gmsh_engine
    from thmstudio.mesh.structured import MeshError
    fake = tmp_path / "fake_gmsh.py"
    fake.write_text("import sys\nsys.stderr.write('OSError: libGLU.so.1: cannot open shared object file: "
                    "No such file or directory\\n')\nsys.exit(1)\n")
    monkeypatch.setattr(gmsh_engine, "gmsh_command", lambda: [sys.executable, str(fake)])
    with pytest.raises(MeshError) as e:
        gmsh_engine.run_gmsh("// empty", tmp_path / "w", 1)
    assert "libGLU.so.1" in str(e.value) and "libglu1-mesa" in str(e.value)


def test_failed_triangle_selftest_blocks_triangle_meshes(tmp_path, monkeypatch):
    from thmstudio import selftest
    from thmstudio.session import Session
    from thmstudio.tools import call
    s = Session(root=tmp_path)
    call(s, "start_from_example", {"example_id": "heated_inclusion"})
    call(s, "build_mesh")
    assert s.mesh["summary"]["element_type"].startswith("Tri")
    monkeypatch.setattr(selftest, "triangles_ok", lambda: (False, "test"))
    rep = call(s, "check_model")
    assert not rep["ok"] and any(i["code"] == "engine_triangles_failed" for i in rep["issues"])
    monkeypatch.setattr(selftest, "triangles_ok", lambda: (True, "test"))
    assert call(s, "check_model")["ok"]
