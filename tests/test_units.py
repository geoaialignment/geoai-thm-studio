import pytest

from thmstudio.units import YEAR, to_si


@pytest.mark.parametrize("value,dim,expected", [
    ("20 degC", "temperature", 293.15), ("20 °C", "temperature", 293.15), ("300 K", "temperature", 300.0),
    (300, "temperature", 300.0), ("5 MPa", "pressure", 5e6), ("1 bar", "pressure", 1e5),
    ("10 yr", "time", 10 * YEAR), ("2 d", "time", 172800.0), ("1 mD", "permeability", 9.869233e-16),
    ("86.4 m/d", "velocity", 1e-3), ("20 %", "dimensionless", 0.2), ({"value": 3, "unit": "W/m/K"}, "thermal_conductivity", 3.0),
    ("864 m3/d", "flow_rate", 0.01), ("1e-5 1/m", "specific_storage", 1e-5),
])
def test_conversions(value, dim, expected):
    assert to_si(value, dim) == pytest.approx(expected, rel=1e-12)


def test_wrong_dimension_names_expected_units():
    with pytest.raises(ValueError, match="pressure unit.*needs temperature"):
        to_si("5 MPa", "temperature")


def test_unknown_unit():
    with pytest.raises(ValueError, match="unknown unit"):
        to_si("5 furlongs", "length")


def test_non_finite_rejected():
    with pytest.raises(ValueError):
        to_si(float("nan"), "length")
