"""Engine self-test for triangle elements, run once per installation and cached.

OpenGeoSys 6.5.8 for Linux x86_64, run under Rosetta emulation on Apple Silicon, returned zero temperatures on
triangle elements, while the same input gave the exact answer on macOS and on quadrilaterals. Whether native Linux is
affected could not be checked, so before a triangle mesh is computed the installed engine solves steady conduction
across a 2 m strip (300 K to 290 K) on triangles, whose exact answer is linear and is reproduced to round-off.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import tempfile
from pathlib import Path

USER = Path(os.environ.get("THMSTUDIO_HOME", Path.home() / ".thmstudio"))
CACHE = USER / "engine_selftest.json"

MODEL = {"name": "selftest", "geometry": {"kind": "rect", "width": 2.0, "layers": [{"name": "rock", "thickness": 1.0}]},
         "physics": {"process": "T"},
         "materials": {"rock": {"thermal_conductivity": 2.0, "density": 2600, "specific_heat": 900}},
         "boundary_conditions": [{"boundary": "left", "variable": "temperature", "value": 300.0},
                                 {"boundary": "right", "variable": "temperature", "value": 290.0}],
         "initial": {"temperature": 295.0}, "mesh": {"size": 0.25}, "study": {"kind": "steady"}}


def _key() -> str:
    from importlib.metadata import version
    return f"ogs {version('ogs')} on {platform.system()} {platform.machine()}"


def _run() -> tuple[bool, str]:
    import numpy as np
    import pyvista as pv

    from .mesh import build_mesh
    from .runner import run_ogs
    from .schema import Model
    from .translator import translate

    model = Model.model_validate(MODEL)
    work = Path(tempfile.mkdtemp(prefix="thmstudio_selftest_"))
    try:
        bundle, _ = build_mesh(model, work / "build")
        br = translate(model, bundle, work / "build")
        bulk = work / "build" / "mesh.vtu"
        pv.read(bulk).triangulate().save(bulk, binary=True)  # same nodes, so the boundary meshes stay valid
        rec = run_ogs(br.prj, work / "run", br.t_end)
        if rec.status != "succeeded":
            return False, f"the engine did not finish the triangle test ({rec.failure})"
        out = sorted((work / "run").glob("*_ts_*.vtu"), key=lambda p: int(p.name.split("_ts_")[1].split("_")[0]))[-1]
        m = pv.read(out)
        err = float(np.abs(m.point_data["temperature"] - (300.0 - 5.0 * m.points[:, 0])).max())
        return err < 1e-6, f"largest temperature error on triangles {err:.3g} K"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def triangles_ok() -> tuple[bool, str]:
    """True if the installed engine solves the triangle test exactly. The result is cached per engine and platform."""
    key = _key()
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    if key not in cache:
        ok, note = _run()
        cache[key] = {"ok": ok, "note": note}
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache, indent=1))
        except OSError:
            pass
    return cache[key]["ok"], f"{cache[key]['note']} ({key})"
