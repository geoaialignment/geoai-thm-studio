"""Mesh-control defects found in the P1 review: grading at well scale, division totals, gmsh divisions,
refusal before allocation, and the default size of every shape."""
import json
import time
from pathlib import Path

import numpy as np
import pytest

from thmstudio.mesh import build_mesh, gmsh_engine, structured
from thmstudio.mesh.structured import MeshError, axis_nodes, default_size
from thmstudio.schema import Model

PKG = Path(__file__).resolve().parents[1] / "src" / "thmstudio"


def case_model(cid: str) -> dict:
    return json.loads((PKG / "cases" / f"{cid}.json").read_text())["model"]


def test_well_grading_matches_request_at_well_scale():
    m = Model.model_validate(case_model("V1b"))  # r from 0.1 to 5000 m, 0.02 m at the well, growth 1.1
    ref = m.mesh.refinements[0]
    (xs, _), *_ = structured.build_axes(m)
    d = np.diff(xs)
    assert abs(d[0] - ref.size) <= 0.1 * ref.size
    graded = d[: int(np.argmax(d >= 0.99 * m.mesh.size))]  # before the plateau at the global size
    assert (graded[1:] / graded[:-1]).max() <= ref.growth * 1.05


def test_division_total_is_not_exceeded():
    x, starts = axis_nodes([0.0, 0.001, 0.002, 100.0], 1.0, [], [None] * 3, [None] * 3, 3)
    assert len(x) - 1 == 3 and starts == [0, 1, 2, 3]
    with pytest.raises(MeshError, match="smaller than the number of layers"):
        axis_nodes([0.0, 1.0, 2.0, 3.0], 1.0, [], [None] * 3, [None] * 3, 2)


def test_gmsh_rejects_divisions():
    d = case_model("V2a-tri")
    d["mesh"]["divisions"] = {"x": 600, "y": 10}
    with pytest.raises(MeshError, match="size and refinements"):
        gmsh_engine.build(Model.model_validate(d), Path("/nonexistent"), 1, "tri")


def test_oversized_request_is_refused_before_allocation():
    d = case_model("V2a")
    d["mesh"] = {"divisions": {"x": 2000, "y": 2000}}
    t = time.time()
    with pytest.raises(MeshError, match="too many elements: about 4,000,000"):
        structured.build(Model.model_validate(d), 1, 600_000)
    d["mesh"] = {"size": 1e-6}
    with pytest.raises(MeshError, match="too many elements"):
        structured.build(Model.model_validate(d), 1, 600_000)
    assert time.time() - t < 1.0


def test_gmsh_estimate_refuses_before_running_gmsh():
    d = case_model("V2d")
    d["mesh"] = {"size": 0.001}
    with pytest.raises(MeshError, match="too many elements"):
        gmsh_engine.build(Model.model_validate(d), Path("/nonexistent"), 1, "tri", 600_000)


def test_every_shape_has_a_default_size():
    for cid in ("V1a", "V1b", "V2a", "V2c", "V2d", "V5"):
        d = case_model(cid)
        d.pop("mesh", None)
        assert default_size(Model.model_validate(d)) > 0


def test_inclusion_builds_with_default_mesh_settings(tmp_path):
    d = case_model("V2d")
    d.pop("mesh", None)
    bundle, rep = build_mesh(Model.model_validate(d), tmp_path)
    assert rep.ok and bundle.engine == "gmsh"
