import math
import xml.etree.ElementTree as ET

import pytest

from thmstudio.mesh import build_mesh
from thmstudio.schema import Model
from thmstudio.translator import TranslationError, time_steps, translate, weighted_measure
from thmstudio.units import G, YEAR


def build(m, work):
    b, rep = build_mesh(m, work)
    br = translate(m, b, work)
    return b, br, ET.parse(br.prj).getroot()


def param(root, name):
    for p in root.iter("parameter"):
        if p.findtext("name") == name:
            return p.findtext("value") or p.findtext("expression")
    raise KeyError(name)


def flow_model(**kw):
    d = dict(geometry={"kind": "rect", "width": 10, "layers": [{"name": "aq", "thickness": 5}]}, physics={"process": "H"},
             materials={"aq": {"hydraulic_conductivity": "1e-5 m/s", "specific_storage": 1e-5, "porosity": 0.2}},
             boundary_conditions=[{"boundary": "left", "variable": "head", "value": "12 m"},
                                  {"boundary": "right", "variable": "head", "kind": "rate", "value": "-0.001 m3/s"}],
             initial={"head": 10}, study={"kind": "transient", "end_time": "1 d", "output_times": ["0.5 d"]})
    d.update(kw)
    return Model(**d)


def test_k_from_hydraulic_conductivity_and_storage(work):
    _, br, root = build(flow_model(), work)
    k = float(root.find(".//medium/properties/property[name='permeability']/value").text)
    assert k == pytest.approx(1e-5 * 1e-3 / (1000 * G))
    s = float(root.find(".//medium/properties/property[name='storage']/value").text)
    assert s == pytest.approx(1e-5 / (1000 * G))
    assert any("permeability" in l for l in br.log)


def test_head_becomes_hydrostatic_pressure_expression(work):
    _, _, root = build(flow_model(), work)
    assert param(root, "bc0_left") == "9810*((12) - y)"
    assert root.findtext(".//process/specific_body_force") == "0 -9.81"
    assert root.findtext(".//process/equation_balance_type") == "volume"


def test_rate_is_spread_over_boundary_length(work):
    _, br, root = build(flow_model(), work)
    assert float(param(root, "bc1_right")) == pytest.approx(-0.001 / 5.0)


def test_axisymmetric_rate_uses_wall_area(work):
    m = Model(geometry={"kind": "axisym_well", "well_radius": 0.1, "outer_radius": 100, "layers": [{"name": "aq", "thickness": 10}]},
              physics={"process": "H", "gravity": False},
              materials={"aq": {"hydraulic_conductivity": 1e-4, "specific_storage": 1e-5}},
              boundary_conditions=[{"boundary": "well", "variable": "head", "kind": "rate", "value": -0.01},
                                   {"boundary": "outer", "variable": "head", "value": 0}],
              initial={"head": 0}, mesh={"size": 5}, study={"kind": "transient", "end_time": 100})
    b, br, root = build(m, work)
    assert float(param(root, "bc0_well")) == pytest.approx(-0.01 / (2 * math.pi * 0.1 * 10), rel=1e-9)
    assert all(e.get("axially_symmetric") == "true" for e in root.iter("mesh") if e.text and e.text.endswith(".vtu"))


def test_transport_flux_is_mass_flux(work):
    m = Model(geometry={"kind": "strip", "segments": [{"name": "c", "thickness": 1}]},
              physics={"process": "HC", "components": [{"name": "tr", "pore_diffusion": 1e-9, "half_life": "10 yr"}]},
              materials={"c": {"permeability": 1e-12, "porosity": 0.3}},
              boundary_conditions=[{"boundary": "left", "variable": "head", "kind": "flux", "value": 1e-6},
                                   {"boundary": "right", "variable": "head", "value": 0}],
              initial={"head": 0}, mesh={"size": 0.1}, study={"kind": "transient", "end_time": 1000})
    _, br, root = build(m, work)
    assert float(param(root, "bc0_left")) == pytest.approx(1e-3)
    decay = float(root.find(".//component/properties/property[name='decay_rate']/value").text)
    assert decay == pytest.approx(math.log(2) / (10 * YEAR))


def test_steady_heat_has_no_capacity(work):
    m = Model(geometry={"kind": "strip", "segments": [{"name": "s", "thickness": 1}]}, physics={"process": "T"},
              materials={"s": {"thermal_conductivity": 2, "density": 2000, "specific_heat": 800}},
              boundary_conditions=[{"boundary": "left", "variable": "temperature", "value": 300}],
              initial={"temperature": 290}, mesh={"size": 0.1}, study={"kind": "steady"})
    _, br, root = build(m, work)
    assert float(root.find(".//property[name='specific_heat_capacity']/value").text) == 0.0
    assert br.t_end == 1.0


def test_bulk_heat_capacity_from_porosity(work):
    m = Model(geometry={"kind": "strip", "segments": [{"name": "s", "thickness": 1}]}, physics={"process": "T"},
              materials={"s": {"thermal_conductivity": 2, "porosity": 0.2, "solid_density": 2700, "solid_specific_heat": 900}},
              boundary_conditions=[{"boundary": "left", "variable": "temperature", "value": 300}],
              initial={"temperature": 290}, mesh={"size": 0.1}, study={"kind": "transient", "end_time": 10})
    _, br, root = build(m, work)
    rho = float(root.find(".//property[name='density']/value").text)
    c = float(root.find(".//property[name='specific_heat_capacity']/value").text)
    assert rho * c == pytest.approx(0.2 * 1000 * 4180 + 0.8 * 2700 * 900)


def test_time_steps_hit_output_times():
    m = flow_model(study={"kind": "transient", "end_time": 100, "first_step": 3, "growth": 1.3, "max_step": 20,
                          "output_times": [10, 50]})
    dts, outs = time_steps(m)
    t = 0.0
    hits = []
    for dt in dts:
        t += dt
        hits.append(t)
    assert outs[0] in hits and outs[1] in hits and outs[-1] == hits[-1]
    assert outs == pytest.approx([10, 50, 100])
    assert max(dts) <= 20 + 1e-12


def test_missing_material_is_a_translation_error(work):
    m = flow_model(materials={})
    b, _ = build_mesh(m, work)
    with pytest.raises(TranslationError, match="no material"):
        translate(m, b, work)
