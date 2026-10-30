"""Units: parse user quantities into SI (temperature in K).

A quantity may be given as a number (already in the SI unit of the field), a
string such as "20 degC" or "1e-5 m/d", or a mapping {"value": 20, "unit": "degC"}.
Each field declares a dimension; a unit of another dimension is an error that
names the expected units.
"""
from __future__ import annotations

import math
import re
from typing import Annotated, Any

from pydantic import BeforeValidator

YEAR = 365.25 * 86400.0
G = 9.81  # m/s2, used for head <-> pressure and K <-> k
DARCY = 9.869233e-13

# unit -> [(dimension, factor, offset)]: SI = value * factor + offset.
# One symbol may serve several dimensions (K, -, kg/m3).
_U: dict[str, list[tuple[str, float, float]]] = {}


def _add(dim: str, names: str, factor: float, offset: float = 0.0) -> None:
    for n in names.split():
        _U.setdefault(n, []).append((dim, factor, offset))


_add("temperature", "K kelvin", 1.0)
_add("temperature", "degC °C C celsius", 1.0, 273.15)
_add("temperature_difference", "K", 1.0)
_add("pressure", "Pa", 1.0)
_add("pressure", "kPa", 1e3)
_add("pressure", "MPa", 1e6)
_add("pressure", "GPa", 1e9)
_add("pressure", "bar", 1e5)
_add("length", "m", 1.0)
_add("length", "cm", 1e-2)
_add("length", "mm", 1e-3)
_add("length", "km", 1e3)
_add("time", "s sec second seconds", 1.0)
_add("time", "min minute minutes", 60.0)
_add("time", "h hr hour hours", 3600.0)
_add("time", "d day days", 86400.0)
_add("time", "a yr year years", YEAR)
_add("permeability", "m2 m^2", 1.0)
_add("permeability", "darcy D", DARCY)
_add("permeability", "mD millidarcy", DARCY * 1e-3)
_add("velocity", "m/s", 1.0)
_add("velocity", "m/d m/day", 1.0 / 86400.0)
_add("velocity", "m/yr m/a m/year", 1.0 / YEAR)
_add("velocity", "cm/s", 1e-2)
_add("thermal_conductivity", "W/m/K W/(m*K) W/(m·K) W/mK", 1.0)
_add("specific_heat", "J/kg/K J/(kg*K) J/(kg·K) J/kgK", 1.0)
_add("specific_heat", "kJ/kg/K", 1e3)
_add("density", "kg/m3 kg/m^3", 1.0)
_add("density", "g/cm3 g/cm^3", 1e3)
_add("power", "W", 1.0)
_add("power", "kW", 1e3)
_add("heat_flux", "W/m2 W/m^2", 1.0)
_add("heat_flux", "mW/m2 mW/m^2", 1e-3)
_add("power_density", "W/m3 W/m^3", 1.0)
_add("specific_storage", "1/m m-1", 1.0)
_add("compressibility", "1/Pa Pa-1", 1.0)
_add("compressibility", "1/MPa", 1e-6)
_add("diffusivity", "m2/s m^2/s", 1.0)
_add("diffusivity", "m2/d m2/day", 1.0 / 86400.0)
_add("diffusivity", "m2/yr m2/a", 1.0 / YEAR)
_add("rate", "1/s s-1", 1.0)
_add("rate", "1/d 1/day", 1.0 / 86400.0)
_add("rate", "1/yr 1/a 1/year", 1.0 / YEAR)
_add("viscosity", "Pa*s Pa·s Pas", 1.0)
_add("viscosity", "mPa*s mPa·s cP", 1e-3)
_add("dimensionless", "- 1", 1.0)
_add("dimensionless", "%", 1e-2)
_add("concentration", "mol/m3 mol/m^3 kg/m3", 1.0)
_add("concentration", "-", 1.0)
_add("flow_rate", "m3/s m^3/s", 1.0)
_add("flow_rate", "m3/d m^3/d m3/day", 1.0 / 86400.0)
_add("flow_rate", "L/s l/s", 1e-3)
_add("mass_flux", "kg/m2/s kg/(m2*s)", 1.0)
_add("concentration_flux", "mol/m2/s kg/m2/s", 1.0)
_add("linear_expansion", "1/K K-1", 1.0)

DIMENSIONS = {d for entries in _U.values() for d, _, _ in entries}


def units_for(dim: str) -> list[str]:
    return [name for name, entries in _U.items() if any(d == dim for d, _, _ in entries)]


def _lookup(unit: str, dim: str) -> tuple[float, float]:
    u = unit.strip()
    hint = ", ".join(units_for(dim)[:8])
    for k in dict.fromkeys((u, u.replace(" ", ""), u.replace("^", ""))):
        entries = _U.get(k)
        if not entries:
            continue
        for d, f, o in entries:
            if d == dim:
                return f, o
        raise ValueError(f"unit '{unit}' is a {entries[0][0]} unit, but this field needs {dim} (use one of: {hint})")
    raise ValueError(f"unknown unit '{unit}' for {dim} (use one of: {hint})")


_NUM = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$")


def to_si(value: Any, dim: str) -> float:
    """Convert a user quantity to SI for the given dimension."""
    if isinstance(value, bool):
        raise ValueError("expected a number with a unit, got true/false")
    if isinstance(value, (int, float)):
        x = float(value)
    elif isinstance(value, str):
        m = _NUM.match(value)
        if not m:
            raise ValueError(f"cannot read '{value}' as a number with a unit")
        num, unit = float(m.group(1)), m.group(2)
        if not unit:
            x = num
        else:
            f, o = _lookup(unit, dim)
            x = num * f + o
    elif isinstance(value, dict) and "value" in value:
        unit = value.get("unit")
        if unit in (None, ""):
            x = float(value["value"])
        else:
            f, o = _lookup(str(unit), dim)
            x = float(value["value"]) * f + o
    else:
        raise ValueError(f"expected a number, a string like '20 degC', or {{value, unit}}; got {value!r}")
    if not math.isfinite(x):
        raise ValueError("value must be finite")
    return x


class Dim(str):
    """Marks the physical dimension of a model field (read by the answer guardrail)."""


def Q(dim: str):
    """Annotated float field that accepts units of one dimension."""
    if dim not in DIMENSIONS:
        raise KeyError(dim)
    return Annotated[float, BeforeValidator(lambda v, _d=dim: to_si(v, _d)), Dim(dim)]


Temperature = Q("temperature")
Pressure = Q("pressure")
Length = Q("length")
Time = Q("time")
Permeability = Q("permeability")
Velocity = Q("velocity")
ThermalConductivity = Q("thermal_conductivity")
SpecificHeat = Q("specific_heat")
Density = Q("density")
Power = Q("power")
HeatFlux = Q("heat_flux")
PowerDensity = Q("power_density")
SpecificStorage = Q("specific_storage")
Compressibility = Q("compressibility")
Diffusivity = Q("diffusivity")
Rate = Q("rate")
Viscosity = Q("viscosity")
Fraction = Q("dimensionless")
Concentration = Q("concentration")
FlowRate = Q("flow_rate")
LinearExpansion = Q("linear_expansion")
