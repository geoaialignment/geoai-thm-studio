"""Boundary segments, corner points and concentration-dependent density (Elder-type models)."""
import xml.etree.ElementTree as ET

import pytest

from thmstudio.check import check_model
from thmstudio.mesh import build_mesh
from thmstudio.schema import Model
from thmstudio.session import Session
from thmstudio.tools import call
from thmstudio.translator import translate


def elder(**kw):
    d = dict(geometry={"kind": "rect", "width": 300, "layers": [{"name": "aq", "thickness": 150}],
                       "segments": [{"name": "src", "side": "top", "start": 150, "end": 300}]},
             physics={"process": "HC", "fluid": {"density_increase_per_concentration": 200},
                      "components": [{"name": "salt", "pore_diffusion": 3.57e-6}]},
             materials={"aq": {"permeability": 4.845e-13, "porosity": 0.1, "longitudinal_dispersivity": 0}},
             boundary_conditions=[{"boundary": "src", "variable": "concentration", "value": 1},
                                  {"boundary": "bottom", "variable": "concentration", "value": 0},
                                  {"boundary": "corner_top_left", "variable": "pressure", "value": 0}],
             initial={"head": 150, "concentration": 0}, mesh={"divisions": {"x": 32, "y": 16}},
             study={"kind": "transient", "end_time": 1e6})
    d.update(kw)
    return Model(**d)


def test_segment_and_corner_meshes(work):
    b, rep = build_mesh(elder(), work)
    assert rep.ok and rep.stats["measures"]["boundary:src"]["mesh"] == pytest.approx(150)
    xs = b.boundaries["src"].points[:, 0]
    assert xs.min() == pytest.approx(150) and xs.max() == pytest.approx(300)
    p = b.point_meshes["corner_top_left"].points[0]
    assert p[0] == 0 and p[1] == 150


def test_density_and_point_condition_in_prj(work):
    m = elder()
    b, _ = build_mesh(m, work)
    root = ET.parse(translate(m, b, work).prj).getroot()
    dens = [p for p in root.iter("property") if p.findtext("name") == "density"][0]
    assert dens.findtext("type") == "Linear" and float(dens.findtext(".//slope")) == pytest.approx(0.2)
    assert dens.findtext(".//variable_name") == "concentration"
    meshes = [bc.findtext("mesh") for bc in root.iter("boundary_condition")]
    assert any(mm.endswith("point_corner_top_left") for mm in meshes)
    assert root.findtext(".//specific_body_force") == "0 -9.81"


def test_buoyant_configuration_and_rules():
    rep = check_model(elder(), None)
    assert rep["configuration"] == "HC-2D-density"
    plan = elder(geometry={"kind": "rect", "width": 300, "layers": [{"name": "aq", "thickness": 150}], "plane": "horizontal"},
                 boundary_conditions=[{"boundary": "left", "variable": "concentration", "value": 1},
                                      {"boundary": "right", "variable": "head", "value": 0}])
    codes = [i["code"] for i in check_model(plan, None)["issues"]]
    assert "density_without_gravity" in codes
    flux_at_point = elder(boundary_conditions=[{"boundary": "corner_top_left", "variable": "head", "kind": "flux", "value": 1e-6}])
    assert "point_condition" in [i["code"] for i in check_model(flux_at_point, None)["issues"]]


def test_segments_through_tools(tmp_path):
    s = Session(root=tmp_path)
    call(s, "new_project", {"name": "e"})
    out = call(s, "set_geometry", {"shape": "rect", "width": "600 m", "layers": [{"name": "aq", "thickness": "150 m"}],
                                   "segments": [{"name": "salt_source", "side": "top", "start": "150 m", "end": "450 m"}]})
    assert out["ok"] and "salt_source" in out["boundaries"] and "corner_top_right" in out["points"]
    call(s, "set_physics", {"process": "HC", "component": {"name": "salt", "pore_diffusion": "3.57e-6 m2/s"},
                            "fluid": [{"name": "density_increase_per_concentration", "value": "200"}]})
    assert s.physics.fluid.density_increase_per_concentration == 200
    call(s, "go_to_step", {"step": "conditions"})
    out = call(s, "set_conditions", {"boundary_conditions": [{"boundary": "corner_top_right", "variable": "pressure", "kind": "fixed", "value": "0 Pa"}]})
    assert out["ok"]
