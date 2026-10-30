import pytest
from pydantic import ValidationError

from thmstudio.schema import Model, boundaries_of, interfaces_of, regions_of

BASE = dict(geometry={"kind": "rect", "width": "10 m", "layers": [{"name": "Clay", "thickness": 2}, {"name": "sand", "thickness": 3}]},
            physics={"process": "T"})


def test_names_normalised_and_listed():
    m = Model(**BASE)
    assert regions_of(m.geometry) == ["clay", "sand"]
    assert "left_clay" in boundaries_of(m.geometry)
    assert interfaces_of(m.geometry) == ["interface_clay_sand"]


def test_hash_ignores_name_and_tracks_values():
    a, b = Model(name="a", **BASE), Model(name="b", **BASE)
    assert a.content_hash() == b.content_hash()
    c = Model(**{**BASE, "geometry": {**BASE["geometry"], "width": 11}})
    assert c.content_hash() != a.content_hash()


def test_porosity_above_one_rejected():
    with pytest.raises(ValidationError):
        Model(**BASE, materials={"clay": {"porosity": 20}})


def test_both_permeability_and_conductivity_rejected():
    with pytest.raises(ValidationError, match="not both"):
        Model(**BASE, materials={"clay": {"permeability": 1e-12, "hydraulic_conductivity": 1e-5}})


def test_inclusion_must_be_inside():
    with pytest.raises(ValidationError, match="inside"):
        Model(geometry={"kind": "rect_inclusion", "width": 4, "height": 4, "center": [1, 2], "radius": 1.5},
              physics={"process": "T"})


def test_condition_units_follow_variable_and_kind():
    m = Model(**BASE, boundary_conditions=[
        {"boundary": "left", "variable": "temperature", "value": "10 degC"},
        {"boundary": "top", "variable": "head", "kind": "rate", "value": "-864 m3/d"},
        {"boundary": "right", "variable": "temperature", "kind": "flux", "value": "50 mW/m2"}])
    assert [bc.value for bc in m.boundary_conditions] == pytest.approx([283.15, -0.01, 0.05])


def test_gravity_defaults():
    assert not Model(**BASE).gravity_on  # heat conduction alone
    assert Model(**{**BASE, "physics": {"process": "H"}}).gravity_on
    plan = {**BASE["geometry"], "plane": "horizontal"}
    assert not Model(geometry=plan, physics={"process": "H"}).gravity_on
