"""Pore-pressure rise 0.5 m from the 300 W point source at 50000 s against the element size at the source.

The point_heat_source example is computed unchanged except for the source refinement size (and, in one extra run, the
time steps the gpt-6-luna answer used). Writes results/point_source_sweep.json.
"""
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pyvista as pv

sys.path.insert(0, "src")
from thmstudio import analytic as an  # noqa: E402
from thmstudio.mesh import build_mesh  # noqa: E402
from thmstudio.post import Results  # noqa: E402
from thmstudio.runner import run_ogs  # noqa: E402
from thmstudio.schema import Model  # noqa: E402
from thmstudio.translator import translate  # noqa: E402

EX = json.loads(Path("src/thmstudio/examples/point_heat_source.json").read_text())["model"]
V5 = json.loads(Path("src/thmstudio/cases/V5.json").read_text())


def params():
    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "point_heat_source":
                return x["params"]
            for v in x.values():
                r = walk(v)
                if r:
                    return r
        if isinstance(x, list):
            for v in x:
                r = walk(v)
                if r:
                    return r
    return walk(V5)


EXACT = float(an.PointHeatSource(**params()).pressure(0.5, 50000.0)[0])
RHO_C = 0.16 * 999.1 * 4280 + 0.84 * 2290 * 917.654
ELL = math.sqrt(1.63992 / RHO_C * 20000.0)  # heat spread by the first output of the example (20000 s)


def run(h, study=None):
    m = json.loads(json.dumps(EX))
    m["mesh"]["refinements"][0]["size"] = f"{h} m"
    if study:
        m["study"].update(study)
    model = Model.model_validate(m)
    work = Path(tempfile.mkdtemp(prefix="thm_sweep_"))
    try:
        bundle, info = build_mesh(model, work / "build")
        br = translate(model, bundle, work / "build")
        rec = run_ogs(br.prj, work / "run", br.t_end, timeout=3000)
        if rec.status != "succeeded":
            return {"h": h, "status": rec.status, "failure": rec.failure}
        res = Results.load(work / "run", model)
        p = float(res.at_points(50000.0, "pressure", np.array([[0.5, 0.0]]))[0])
        T = float(res.at_points(50000.0, "temperature", np.array([[0.5, 0.0]]))[0])
        n = pv.read(work / "build" / "mesh.vtu").n_cells
        return {"h": h, "h_over_ell": h / ELL, "pressure_MPa": p / 1e6, "error_pct": (p - EXACT) / EXACT * 100,
                "temperature_rise_K": T - 273.15, "cells": n, "study": study}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    rows = []
    for h in [0.2, 0.1, 0.0579, 0.05, 0.0289, 0.0145, 0.01, 0.005]:
        r = run(h)
        print(r, flush=True)
        rows.append(r)
    r = run(0.05, {"first_step": "100 s", "max_step": "5000 s", "output_times": ["50000 s"]})
    print(r, flush=True)
    rows.append(r)
    Path("results").mkdir(exist_ok=True)
    json.dump({"exact_MPa": EXACT / 1e6, "ell_m": ELL, "first_output_s": 20000, "rows": rows},
              open("results/point_source_sweep.json", "w"), indent=1)
