"""P2: G4 mesh, mechanics translation, mechanics checks, tool flow."""
import json
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from thmstudio.check import check_model
from thmstudio.mesh import build_mesh
from thmstudio.schema import Model
from thmstudio.session import Session
from thmstudio.tools import call
from thmstudio.translator import translate

REPO = {"kind": "axisym_source", "outer_radius": 20, "height": 20, "symmetric": False, "source": "canister",
        "canister_radius": 0.5, "canister_length": 4.0, "buffer_radius": 0.9, "buffer_length": 6.0}
ROCK = {"permeability": 1e-18, "porosity": 0.01, "youngs_modulus": 5e10, "poissons_ratio": 0.25, "thermal_conductivity": 3,
        "solid_density": 2650, "solid_specific_heat": 850, "thermal_expansion": 1e-5, "biot_coefficient": 1}


def thm(geometry=REPO, **kw):
    d = dict(geometry=geometry, physics={"process": "THM"}, materials={r: ROCK for r in ("rock", "canister", "buffer")},
             boundary_conditions=[{"boundary": "outer", "variable": "temperature", "value": 290},
                                  {"boundary": "outer", "variable": "pressure", "value": 0},
                                  {"boundary": "bottom", "variable": "displacement", "kind": "roller"}],
             heat_sources=[{"region": "canister", "kind": "power", "value": 1000}],
             initial={"temperature": 290, "pressure": 0}, mesh={"size": 2, "refinements": [{"target": "buffer_rock", "size": 0.1}]},
             study={"kind": "transient", "end_time": 1e6})
    d.update(kw)
    return Model(**d)


def test_g4_regions_interfaces_and_order(work):
    b, rep = build_mesh(thm(), work)
    assert rep.ok and b.order == 2 and b.cell_type == "Quad8"
    m = rep.stats["measures"]
    assert m["region:canister"]["mesh"] == pytest.approx(0.5 * 4.0)
    assert m["region:buffer"]["mesh"] == pytest.approx(0.9 * 6.0 - 2.0)
    assert m["boundary:canister_surface"]["mesh"] == pytest.approx(2 * 0.5 + 4.0)
    assert b.bulk.points[:, 0].min() == 0.0


def test_point_source_mesh_and_half_power(work):
    g = {"kind": "axisym_source", "outer_radius": 5, "height": 5, "symmetric": True, "source": "point"}
    m = thm(geometry=g, materials={"rock": ROCK}, heat_sources=[{"region": "source", "kind": "power", "value": 300}],
            mesh={"size": 0.5, "refinements": [{"target": "source", "size": 0.05}]})
    b, _ = build_mesh(m, work)
    pm = b.point_meshes["source"]
    assert pm.n_points == 1 and np.allclose(b.bulk.points[int(pm.point_data["bulk_node_ids"][0])], 0.0)
    br = translate(m, b, work)
    root = ET.parse(br.prj).getroot()
    st = root.find(".//source_term")
    assert st.findtext("type") == "Nodal"
    name = st.findtext("parameter")
    val = [p.findtext("value") for p in root.iter("parameter") if p.findtext("name") == name][0]
    assert float(val) == pytest.approx(150.0)


def test_canister_power_density_counts_both_halves(work):
    g = dict(REPO, symmetric=True, height=10)
    m = thm(geometry=g)
    b, _ = build_mesh(m, work)
    br = translate(m, b, work)
    root = ET.parse(br.prj).getroot()
    name = root.find(".//source_term").findtext("parameter")
    val = float([p.findtext("value") for p in root.iter("parameter") if p.findtext("name") == name][0])
    assert val == pytest.approx(1000 / (math.pi * 0.5 ** 2 * 4.0), rel=1e-9)


def test_axis_gets_radial_roller_and_groups(work):
    m = thm()
    b, _ = build_mesh(m, work)
    br = translate(m, b, work)
    root = ET.parse(br.prj).getroot()
    disp = [pv for pv in root.iter("process_variable") if pv.findtext("name") == "displacement"][0]
    assert disp.findtext("order") == "2" and disp.findtext("components") == "2"
    meshes = [bc.findtext("mesh") for bc in disp.iter("boundary_condition")]
    assert any(mm.endswith("boundary_axis") for mm in meshes)
    E = [p for p in root.iter("parameter") if p.findtext("name") == "E"][0]
    assert E.findtext("type") == "Group" and len(E.findall("index_values")) == 3
    assert root.findtext(".//process/equation_balance_type") == "mass"
    assert root.findtext(".//process/integration_order") == "3"


def test_load_sign_and_roller_component(work):
    m = Model(geometry={"kind": "rect", "width": 1, "layers": [{"name": "s", "thickness": 2}]}, physics={"process": "TM"},
              materials={"s": {"thermal_conductivity": 2, "density": 2000, "specific_heat": 900, "youngs_modulus": 1e9,
                               "poissons_ratio": 0.3, "thermal_expansion": 1e-5}},
              boundary_conditions=[{"boundary": "left", "variable": "displacement", "kind": "roller"},
                                   {"boundary": "bottom", "variable": "displacement", "kind": "roller"},
                                   {"boundary": "top", "variable": "displacement", "kind": "load", "value": "1 MPa"},
                                   {"boundary": "top", "variable": "temperature", "value": 300}],
              initial={"temperature": 300}, mesh={"size": 0.5}, study={"kind": "steady"})
    b, _ = build_mesh(m, work)
    root = ET.parse(translate(m, b, work).prj).getroot()
    bcs = {bc.findtext("mesh").split("_")[-1]: bc for bc in root.iter("boundary_condition")
           if bc.findtext("component") is not None}
    assert bcs["left"].findtext("component") == "0" and bcs["bottom"].findtext("component") == "1"
    top = bcs["top"]
    assert top.findtext("type") == "Neumann" and top.findtext("component") == "1"
    val = [p.findtext("value") for p in root.iter("parameter") if p.findtext("name") == top.findtext("parameter")][0]
    assert float(val) == -1e6


def test_rigid_body_and_gravity_rules():
    base = dict(geometry={"kind": "rect", "width": 1, "layers": [{"name": "s", "thickness": 2}]}, physics={"process": "TM"},
                materials={"s": {"thermal_conductivity": 2, "density": 2000, "specific_heat": 900, "youngs_modulus": 1e9,
                                 "poissons_ratio": 0.3, "thermal_expansion": 1e-5}},
                initial={"temperature": 300}, study={"kind": "steady"})
    only_x = Model(**base, boundary_conditions=[{"boundary": "left", "variable": "displacement", "kind": "roller"},
                                                {"boundary": "top", "variable": "temperature", "value": 300}])
    codes = [i["code"] for i in check_model(only_x, None)["issues"]]
    assert "rigid_body" in codes
    grav = Model(**{**base, "physics": {"process": "TM", "gravity": True}},
                 boundary_conditions=[{"boundary": "bottom", "variable": "displacement", "kind": "fixed"},
                                      {"boundary": "top", "variable": "temperature", "value": 300}])
    codes = [i["code"] for i in check_model(grav, None)["issues"]]
    assert "gravity_with_mechanics" in codes and "rigid_body" not in codes


def test_water_flux_with_mechanics_refused():
    m = thm(boundary_conditions=[{"boundary": "outer", "variable": "head", "kind": "flux", "value": 1e-9},
                                 {"boundary": "top", "variable": "pressure", "value": 0},
                                 {"boundary": "outer", "variable": "temperature", "value": 290},
                                 {"boundary": "bottom", "variable": "displacement", "kind": "roller"}])
    assert "unverified_condition" in [i["code"] for i in check_model(m, None)["issues"]]


def test_unsupported_mechanics_shape():
    m = Model(geometry={"kind": "box", "length_x": 1, "length_y": 1, "layers": [{"name": "s", "thickness": 1}]},
              physics={"process": "TM"})
    codes = [i["code"] for i in check_model(m, None)["issues"]]
    assert "unsupported_configuration" in codes


def test_tm_example_flow_and_stress_component(tmp_path):
    s = Session(root=tmp_path)
    out = call(s, "start_from_example", {"example_id": "heated_block_tm", "changes": [{"name": "duration", "value": "20 d"}]})
    assert out["ok"], out
    assert call(s, "build_mesh")["ok"]
    assert call(s, "check_model")["ok"]
    assert call(s, "run")["ok"]
    for _ in range(100):
        st = call(s, "run_status")
        if st.get("status") in ("succeeded", "failed"):
            break
    assert st["status"] == "succeeded", st
    out = call(s, "show_results", {"field": "sigma", "component": "xx", "kind": "map"})
    assert out["ok"] and out["min"] < 0  # confined heating: compression


def test_set_conditions_roller_without_value(tmp_path):
    s = Session(root=tmp_path)
    call(s, "start_from_example", {"example_id": "consolidation_column"})
    call(s, "go_to_step", {"step": "conditions"})
    out = call(s, "set_conditions", {"boundary_conditions": [{"boundary": "left", "variable": "displacement", "kind": "roller"}]})
    assert out["ok"], out


def test_full_model_point_source_gets_whole_power(work):
    g = {"kind": "axisym_source", "outer_radius": 5, "height": 10, "symmetric": False, "source": "point"}
    m = thm(geometry=g, materials={"rock": ROCK}, heat_sources=[{"region": "source", "kind": "power", "value": 300}],
            mesh={"size": 0.5, "refinements": [{"target": "source", "size": 0.05}]})
    b, _ = build_mesh(m, work)
    root = ET.parse(translate(m, b, work).prj).getroot()
    name = root.find(".//source_term").findtext("parameter")
    assert float([p.findtext("value") for p in root.iter("parameter") if p.findtext("name") == name][0]) == 300.0


def test_conflicting_mechanics_and_axis_rules():
    base = [{"boundary": "outer", "variable": "temperature", "value": 290}, {"boundary": "outer", "variable": "pressure", "value": 0}]
    two = thm(boundary_conditions=base + [{"boundary": "bottom", "variable": "displacement", "kind": "roller"},
                                          {"boundary": "bottom", "variable": "displacement", "kind": "load", "value": 1e5}])
    assert "conflicting_condition" in [i["code"] for i in check_model(two, None)["issues"]]
    # a user condition on the axis replaces the automatic u_r = 0, so the axis no longer counts for r
    axis_z = thm(boundary_conditions=base + [{"boundary": "axis", "variable": "displacement", "kind": "fixed", "component": "z", "value": 0}])
    assert "rigid_body" in [i["code"] for i in check_model(axis_z, None)["issues"]]


def test_conductivity_below_water_share_rejected():
    m = thm(materials={r: {**ROCK, "porosity": 0.5, "thermal_conductivity": 0.2} for r in ("rock", "canister", "buffer")})
    assert "conductivity_too_low" in [i["code"] for i in check_model(m, None)["issues"]]
