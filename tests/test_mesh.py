import math
import sys

import numpy as np
import pytest

from thmstudio.mesh import build_mesh, choose
from thmstudio.mesh.contract import QUADRATIC_QUAD
from thmstudio.mesh import structured
from thmstudio.schema import Model

SHAPES = {
    "rect": {"kind": "rect", "width": 20, "layers": [{"name": "a", "thickness": 3}, {"name": "b", "thickness": 7}]},
    "strip": {"kind": "strip", "segments": [{"name": "a", "thickness": 4}, {"name": "b", "thickness": 6}], "width": 0.5},
    "well": {"kind": "axisym_well", "well_radius": 0.1, "outer_radius": 50, "layers": [{"name": "a", "thickness": 2}, {"name": "b", "thickness": 3}]},
    "box": {"kind": "box", "length_x": 4, "length_y": 3, "layers": [{"name": "a", "thickness": 1}, {"name": "b", "thickness": 2}]},
    "inclusion": {"kind": "rect_inclusion", "width": 10, "height": 6, "center": [5, 3], "radius": 1},
}


def model(shape, **mesh):
    return Model(geometry=SHAPES[shape], physics={"process": "T"}, mesh=mesh)


@pytest.mark.parametrize("shape", list(SHAPES))
def test_shapes_pass_quality_and_measures(shape, work):
    m = model(shape, size=0.5 if shape != "well" else 2.0)
    b, rep = build_mesh(m, work)
    assert rep.ok, rep.as_dict()["issues"]
    assert set(b.regions) == set(m.materials) | set(b.regions)
    assert rep.stats["ogs_checkMesh"]["clean"]


@pytest.mark.parametrize("shape", ["rect", "inclusion", "box"])
def test_deterministic_files(shape, work):
    m = model(shape, size=0.7)
    _, r1 = build_mesh(m, work / "1")
    _, r2 = build_mesh(m, work / "2")
    assert r1.stats["file_hash"] == r2.stats["file_hash"]


def test_material_ids_follow_layers(work):
    b, _ = build_mesh(model("rect", size=0.5), work)
    c = b.bulk.cell_centers().points
    mats = np.asarray(b.bulk.cell_data["MaterialIDs"])
    assert np.all(mats[c[:, 1] < 3] == 0) and np.all(mats[c[:, 1] > 3] == 1)


def test_refinement_grades_towards_target(work):
    m = model("rect", size=1.0, refinements=[{"target": "interface_a_b", "size": 0.05, "growth": 1.2}])
    b, rep = build_mesh(m, work)
    ys = np.unique(np.round(b.bulk.points[:, 1], 9))
    dy = np.diff(ys)
    i = np.argmin(np.abs(ys - 3.0))
    assert dy[i - 1] == pytest.approx(0.05, rel=0.3) and dy.max() == pytest.approx(1.0, rel=0.3)
    assert np.all(dy[1:] / dy[:-1] < 1.35) and np.all(dy[:-1] / dy[1:] < 1.35)


def test_divisions_override(work):
    b, _ = build_mesh(model("rect", size=1.0, divisions={"x": 7, "a": 3, "b": 4}), work)
    assert b.bulk.n_cells == 7 * 7


def test_quadratic_mid_nodes(work):
    bulk, bnd = None, None
    m = model("rect", size=1.0)
    b = structured.build(m, order=2)
    assert int(b.bulk.celltypes[0]) == QUADRATIC_QUAD
    conn = b.bulk.cell_connectivity.reshape(b.bulk.n_cells, 8)
    P = b.bulk.points
    for a_, b_, mid in ((0, 1, 4), (1, 2, 5), (2, 3, 6), (3, 0, 7)):
        assert np.allclose(0.5 * (P[conn[:, a_]] + P[conn[:, b_]]), P[conn[:, mid]])
    assert all(int(g.celltypes[0]) == 21 for g in b.boundaries.values())


def test_axisymmetric_radius_positive(work):
    b, rep = build_mesh(model("well", size=2.0, refinements=[{"target": "well", "size": 0.01, "growth": 1.1}]), work)
    assert b.axisymmetric and b.bulk.points[:, 0].min() == pytest.approx(0.1)


def test_two_engines_agree_on_measures(work):
    quad, rq = build_mesh(model("rect", size=0.5, element="quad"), work / "q")
    tri, rt = build_mesh(model("rect", size=0.5, element="tri"), work / "t")
    assert quad.engine == "structured" and tri.engine == "gmsh"
    for k, v in rq.stats["measures"].items():
        assert rt.stats["measures"][k]["mesh"] == pytest.approx(v["mesh"], rel=1e-9)


def test_inclusion_area_and_circumference(work):
    b, rep = build_mesh(model("inclusion", size=0.3, refinements=[{"target": "inclusion_boundary", "size": 0.03}]), work)
    meas = rep.stats["measures"]
    assert meas["region:inclusion"]["mesh"] == pytest.approx(math.pi, rel=1e-3)
    assert meas["boundary:inclusion_boundary"]["mesh"] == pytest.approx(2 * math.pi, rel=1e-3)
    assert meas["region:matrix"]["mesh"] + meas["region:inclusion"]["mesh"] == pytest.approx(60.0, rel=1e-12)


def test_bad_refinement_target_names_options(work):
    with pytest.raises(ValueError, match="choose from"):
        build_mesh(model("rect", refinements=[{"target": "lft", "size": 0.1}]), work)


def test_engine_choice():
    assert choose(model("inclusion")) == ("gmsh", "tri")
    assert choose(model("rect")) == ("structured", "quad")
    assert choose(model("box")) == ("structured", "hex")


def test_gmsh_never_imported(work):
    build_mesh(model("inclusion", size=0.5), work)
    assert "gmsh" not in sys.modules


def test_boundary_ids_match_ogs_identify_subdomains(work):
    """bulk_node_ids / bulk_element_ids equal what OGS identifySubdomains computes."""
    import subprocess
    import pyvista as pv
    for shape in ("rect", "inclusion"):
        d = work / shape
        b, _ = build_mesh(model(shape, size=0.5), d)
        names = list(b.boundaries)
        for n in names:
            g = b.boundaries[n].copy()
            g.point_data.clear(); g.cell_data.clear()
            g.save(d / f"chk_{n}.vtu")
        exe = sys.executable.replace("python", "identifySubdomains")
        subprocess.run([exe, "-f", "-m", "mesh.vtu", "-o", "ids_"] + [f"chk_{n}.vtu" for n in names],
                       cwd=d, check=True, capture_output=True)
        for n in names:
            c = pv.read(d / f"ids_chk_{n}.vtu")
            assert np.array_equal(c.point_data["bulk_node_ids"], b.boundaries[n].point_data["bulk_node_ids"]), n
            assert np.array_equal(np.asarray(c.cell_data["bulk_element_ids"]).ravel(),
                                  b.boundaries[n].cell_data["bulk_element_ids"]), n
