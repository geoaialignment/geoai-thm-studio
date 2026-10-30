"""Model tree: the only description of a model the agent can change.

The tree mirrors the steps of a multiphysics GUI: geometry, materials, physics, conditions,
mesh, study. Every quantity is stored in SI (temperature in K). Values the user
did not give stay unset, so reports can tell user values from defaults.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .units import (Concentration, Density, Diffusivity, FlowRate, Fraction, HeatFlux, Length, LinearExpansion,
                    Permeability, Power, PowerDensity, Pressure, Rate, SpecificHeat, SpecificStorage,
                    Temperature, ThermalConductivity, Time, Velocity, Viscosity, to_si)

SCHEMA_VERSION = 1
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _name(v: str) -> str:
    v = str(v).strip().lower().replace(" ", "_").replace("-", "_")
    if not NAME_RE.match(v):
        raise ValueError(f"name '{v}' must start with a letter and use only a-z, 0-9 and _ (max 32)")
    return v


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------- geometry

class Layer(Strict):
    name: str
    thickness: Length = Field(gt=0)

    v_names = field_validator("name")(lambda cls, v: _name(v))


class BoundarySegment(Strict):
    """A named part of the top or bottom side, from x = start to x = end."""
    name: str
    side: Literal["top", "bottom"]
    start: Length = Field(ge=0)
    end: Length = Field(gt=0)

    v_names = field_validator("name")(lambda cls, v: _name(v))


class RectGeometry(Strict):
    """G1: 2D rectangle, x in [0, width], y from the bottom. Layers stack bottom to top.
    Named segments of the top or bottom side can carry their own conditions."""
    kind: Literal["rect"] = "rect"
    width: Length = Field(gt=0)
    layers: list[Layer] = Field(min_length=1, max_length=8)
    plane: Literal["vertical", "horizontal"] = "vertical"
    segments: list[BoundarySegment] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _segments(self):
        names = [l.name for l in self.layers]
        for sg in self.segments:
            if not 0 <= sg.start < sg.end <= self.width:
                raise ValueError(f"segment '{sg.name}' must satisfy 0 <= start < end <= width")
            if sg.name in names or sg.name in ("left", "right", "top", "bottom"):
                raise ValueError(f"segment name '{sg.name}' is already used")
        return self


class InclusionGeometry(Strict):
    """G2: 2D rectangle with one circular inclusion."""
    kind: Literal["rect_inclusion"] = "rect_inclusion"
    width: Length = Field(gt=0)
    height: Length = Field(gt=0)
    center: tuple[Length, Length]
    radius: Length = Field(gt=0)
    matrix: str = "matrix"
    inclusion: str = "inclusion"
    plane: Literal["vertical", "horizontal"] = "vertical"

    v_names = field_validator("matrix", "inclusion")(lambda cls, v: _name(v))

    @model_validator(mode="after")
    def _inside(self):
        (xc, yc), r = self.center, self.radius
        if not (xc - r > 0 and xc + r < self.width and yc - r > 0 and yc + r < self.height):
            raise ValueError("the inclusion must lie inside the rectangle without touching its sides")
        if self.matrix == self.inclusion:
            raise ValueError("matrix and inclusion need different names")
        return self


class AxisymWellGeometry(Strict):
    """G3: axisymmetric r-z section from the well wall (r = well_radius) to outer_radius."""
    kind: Literal["axisym_well"] = "axisym_well"
    well_radius: Length = Field(gt=0)
    outer_radius: Length = Field(gt=0)
    layers: list[Layer] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _radii(self):
        if self.outer_radius <= self.well_radius:
            raise ValueError("outer_radius must be larger than well_radius")
        return self


class AxisymSourceGeometry(Strict):
    """G4: axisymmetric r-z section with a heat source on the axis (a point or a canister),
    optionally inside a buffer (deposition hole). With symmetric=True only the upper half is
    modelled (z from 0 to height) and the bottom is the symmetry plane through the source;
    otherwise z runs from -height/2 to height/2. The source centre is at r = 0, z = 0."""
    kind: Literal["axisym_source"] = "axisym_source"
    outer_radius: Length = Field(gt=0)
    height: Length = Field(gt=0)
    symmetric: bool = True
    source: Literal["point", "canister"] = "point"
    canister_radius: Length | None = Field(default=None, gt=0)
    canister_length: Length | None = Field(default=None, gt=0)
    buffer_radius: Length | None = Field(default=None, gt=0)
    buffer_length: Length | None = Field(default=None, gt=0)
    rock: str = "rock"
    canister: str = "canister"
    buffer: str = "buffer"

    v_names = field_validator("rock", "canister", "buffer")(lambda cls, v: _name(v))

    @model_validator(mode="after")
    def _parts(self):
        half = self.height if self.symmetric else self.height / 2
        if self.source == "canister":
            if self.canister_radius is None or self.canister_length is None:
                raise ValueError("a canister source needs canister_radius and canister_length")
            if self.canister_radius >= self.outer_radius or self.canister_length / 2 >= half:
                raise ValueError("the canister must lie inside the model")
        elif self.canister_radius is not None or self.canister_length is not None:
            raise ValueError("canister_radius and canister_length are only used with source 'canister'")
        if (self.buffer_radius is None) != (self.buffer_length is None):
            raise ValueError("a buffer needs buffer_radius and buffer_length")
        if self.buffer_radius is not None:
            if self.source != "canister":
                raise ValueError("a buffer surrounds a canister; use source 'canister'")
            if not (self.canister_radius < self.buffer_radius < self.outer_radius
                    and self.canister_length < self.buffer_length and self.buffer_length / 2 < half):
                raise ValueError("the buffer must enclose the canister and lie inside the model")
        if len({self.rock, self.canister, self.buffer}) < 3:
            raise ValueError("rock, canister and buffer need different names")
        return self


class BoxGeometry(Strict):
    """G5: 3D box, x in [0, length_x], y in [0, length_y], layers stack in z from the bottom."""
    kind: Literal["box"] = "box"
    length_x: Length = Field(gt=0)
    length_y: Length = Field(gt=0)
    layers: list[Layer] = Field(min_length=1, max_length=8)


class StripGeometry(Strict):
    """G6: thin 2D strip along x for 1D checks. Segments follow each other along x."""
    kind: Literal["strip"] = "strip"
    segments: list[Layer] = Field(min_length=1, max_length=8)
    width: Length = Field(default=1.0, gt=0)


Geometry = Annotated[Union[RectGeometry, InclusionGeometry, AxisymWellGeometry, AxisymSourceGeometry, BoxGeometry,
                           StripGeometry],
                     Field(discriminator="kind")]


def regions_of(g) -> list[str]:
    if g.kind == "rect_inclusion":
        return [g.matrix, g.inclusion]
    if g.kind == "axisym_source":
        return [g.rock] + ([g.canister] if g.source == "canister" else []) + ([g.buffer] if g.buffer_radius else [])
    if g.kind == "strip":
        return [s.name for s in g.segments]
    return [l.name for l in g.layers]


def boundaries_of(g) -> list[str]:
    """Named boundaries a condition may use (internal interfaces excluded)."""
    if g.kind in ("rect", "strip"):
        out = ["left", "right", "bottom", "top"]
        parts = g.layers if g.kind == "rect" else g.segments
        if len(parts) > 1:
            sides = ("left", "right") if g.kind == "rect" else ("bottom", "top")
            out += [f"{s}_{p.name}" for s in sides for p in parts]
        if g.kind == "rect":
            out += [sg.name for sg in g.segments]
        return out
    if g.kind == "rect_inclusion":
        return ["left", "right", "bottom", "top"]
    if g.kind == "axisym_well":
        out = ["well", "outer", "bottom", "top"]
        if len(g.layers) > 1:
            out += [f"{s}_{l.name}" for s in ("well", "outer") for l in g.layers]
        return out
    if g.kind == "axisym_source":
        return ["axis", "outer", "bottom", "top"]
    if g.kind == "box":
        return ["left", "right", "front", "back", "bottom", "top"]
    raise ValueError(g.kind)


CORNERS = ("corner_bottom_left", "corner_bottom_right", "corner_top_left", "corner_top_right")


def points_of(g) -> list[str]:
    """Named points: the point source of G4; the corners of a rectangle (e.g. a pressure reference)."""
    if g.kind == "axisym_source" and g.source == "point":
        return ["source"]
    if g.kind == "rect":
        return list(CORNERS)
    return []


# outward normal of each named boundary: (axis index, sign)
_NORMALS = {"left": (0, -1), "right": (0, 1), "well": (0, -1), "outer": (0, 1), "axis": (0, -1)}


def boundary_normal(g, name: str) -> tuple[int, int]:
    base = name
    if g.kind == "rect":
        for sg in g.segments:
            if sg.name == name:
                base = sg.side
    for side in ("left", "right", "bottom", "top", "well", "outer", "front", "back", "axis"):
        if name == side or name.startswith(side + "_"):
            base = side
            break
    if g.kind == "box":
        return {"left": (0, -1), "right": (0, 1), "front": (1, -1), "back": (1, 1), "bottom": (2, -1),
                "top": (2, 1)}[base]
    return {**_NORMALS, "bottom": (1, -1), "top": (1, 1)}[base]


def interfaces_of(g) -> list[str]:
    """Internal interfaces: for value extraction only, never for conditions."""
    if g.kind == "rect_inclusion":
        return ["inclusion_boundary"]
    if g.kind == "axisym_source":
        return (["canister_surface"] if g.source == "canister" else []) + (["buffer_rock"] if g.buffer_radius else [])
    parts = g.segments if g.kind == "strip" else g.layers
    return [f"interface_{a.name}_{b.name}" for a, b in zip(parts, parts[1:])]


def dimension_of(g) -> int:
    return 3 if g.kind == "box" else 2


def is_axisymmetric(g) -> bool:
    return g.kind in ("axisym_well", "axisym_source")


def vertical_axis(g) -> str | None:
    """Coordinate that points up, or None for a horizontal (plan view) model."""
    if g.kind == "box":
        return "z"
    if g.kind == "strip":
        return None
    if g.kind in ("rect", "rect_inclusion") and g.plane == "horizontal":
        return None
    return "y"


# ---------------------------------------------------------------- materials

class Material(Strict):
    """Properties of one region. Which ones are needed depends on the physics."""
    label: str | None = None  # library name or the user's own name, for reports
    # hydraulic
    permeability: Permeability | None = Field(default=None, gt=0)
    hydraulic_conductivity: Velocity | None = Field(default=None, gt=0)
    porosity: Fraction | None = Field(default=None, gt=0, le=1)
    specific_storage: SpecificStorage | None = Field(default=None, ge=0)
    # thermal: effective (saturated bulk) conductivity; heat capacity of the solid grains
    thermal_conductivity: ThermalConductivity | None = Field(default=None, gt=0)
    solid_density: Density | None = Field(default=None, gt=0)
    solid_specific_heat: SpecificHeat | None = Field(default=None, gt=0)
    # bulk heat capacity, used by heat conduction alone when given
    density: Density | None = Field(default=None, gt=0)
    specific_heat: SpecificHeat | None = Field(default=None, gt=0)
    # transport
    longitudinal_dispersivity: Length | None = Field(default=None, ge=0)
    transverse_dispersivity: Length | None = Field(default=None, ge=0)
    # mechanics (linear elastic, isotropic)
    youngs_modulus: Pressure | None = Field(default=None, gt=0)
    poissons_ratio: Fraction | None = Field(default=None, ge=0, lt=0.5)
    biot_coefficient: Fraction | None = Field(default=None, ge=0, le=1)  # 0 switches the coupling off
    thermal_expansion: LinearExpansion | None = Field(default=None, ge=0)  # linear, of the solid

    @model_validator(mode="after")
    def _one_hydraulic(self):
        if self.permeability is not None and self.hydraulic_conductivity is not None:
            raise ValueError("give permeability or hydraulic_conductivity, not both")
        return self


# ---------------------------------------------------------------- physics

class Fluid(Strict):
    density: Density = Field(default=1000.0, gt=0)
    viscosity: Viscosity = Field(default=1.0e-3, gt=0)
    specific_heat: SpecificHeat = Field(default=4180.0, gt=0)
    thermal_conductivity: ThermalConductivity = Field(default=0.6, gt=0)
    thermal_expansion: LinearExpansion = Field(default=4.0e-4, ge=0)  # volumetric; water near 50 degC
    # density increase per unit concentration (kg/m3), e.g. 200 for brine that is 1200 kg/m3 at c = 1;
    # 0 means the density does not depend on concentration (no buoyancy)
    density_increase_per_concentration: float = Field(default=0.0, ge=0, le=1000)


class Component(Strict):
    """A dissolved component carried by the water (no reactions)."""
    name: str = "c"
    pore_diffusion: Diffusivity = Field(ge=0)
    decay_rate: Rate | None = Field(default=None, ge=0)
    half_life: Time | None = Field(default=None, gt=0)
    retardation: float | dict[str, float] = 1.0

    v_names = field_validator("name")(lambda cls, v: _name(v))

    @model_validator(mode="after")
    def _decay(self):
        if self.decay_rate is not None and self.half_life is not None:
            raise ValueError("give decay_rate or half_life, not both")
        rs = self.retardation.values() if isinstance(self.retardation, dict) else [self.retardation]
        if any(r < 1 for r in rs):
            raise ValueError("retardation factors must be >= 1")
        return self

    @property
    def decay(self) -> float:
        import math
        if self.half_life is not None:
            return math.log(2.0) / self.half_life
        return self.decay_rate or 0.0


Process = Literal["H", "T", "TH", "HC", "HM", "TM", "THM"]
MECHANICS = ("HM", "TM", "THM")


class Physics(Strict):
    process: Process
    gravity: bool | None = None  # None: on for vertical sections, off for plan views
    fluid: Fluid = Field(default_factory=Fluid)
    components: list[Component] = Field(default_factory=list, max_length=1)


VARIABLES = {"H": ("head", "pressure"), "T": ("temperature",), "TH": ("temperature", "head", "pressure"),
             "HC": ("head", "pressure", "concentration"), "HM": ("head", "pressure", "displacement"),
             "TM": ("temperature", "displacement"), "THM": ("temperature", "head", "pressure", "displacement")}


# ---------------------------------------------------------------- conditions

_FIXED_DIM = {"head": "length", "pressure": "pressure", "temperature": "temperature",
              "concentration": "concentration", "displacement": "length"}
# flux: per unit area of the boundary; rate: total over the boundary
_FLUX_DIM = {"head": "velocity", "pressure": "velocity", "temperature": "heat_flux",
             "concentration": "concentration_flux"}
_RATE_DIM = {"head": "flow_rate", "pressure": "flow_rate", "temperature": "power"}


class BoundaryCondition(Strict):
    """kind 'fixed' holds a value; 'flux' is inflow per area (negative = outflow);
    'rate' is the total inflow over the whole boundary (water m3/s or heat W).
    Displacement: 'roller' (no movement across the boundary), 'fixed' (one component, or all
    if component is not given) and 'load' (normal pressure on the boundary, compression positive)."""
    boundary: str
    variable: Literal["head", "pressure", "temperature", "concentration", "displacement"]
    kind: Literal["fixed", "flux", "rate", "roller", "load"] = "fixed"
    value: float = 0.0
    component: Literal["x", "y", "z", "r"] | None = None
    expression: str | None = Field(default=None, exclude=False)  # verification only, never from tools

    v_names = field_validator("boundary")(lambda cls, v: _name(v))

    @model_validator(mode="before")
    @classmethod
    def _units(cls, data):
        if isinstance(data, dict) and "value" in data and not isinstance(data["value"], float):
            var, kind = data.get("variable"), data.get("kind", "fixed")
            table = {"fixed": _FIXED_DIM, "flux": _FLUX_DIM, "rate": _RATE_DIM,
                     "load": {"displacement": "pressure"}}.get(kind, {})
            dim = table.get(var)
            if dim:
                data = {**data, "value": to_si(data["value"], dim)}
        return data

    @model_validator(mode="after")
    def _kind(self):
        if self.kind == "rate" and self.variable == "concentration":
            raise ValueError("a total rate is not available for concentration; use flux")
        mech_kinds = ("roller", "load")
        if self.variable == "displacement":
            if self.kind not in ("fixed",) + mech_kinds:
                raise ValueError("displacement conditions are 'roller', 'fixed' or 'load'")
        elif self.kind in mech_kinds:
            raise ValueError(f"'{self.kind}' is a displacement condition")
        if self.component is not None and not (self.variable == "displacement" and self.kind == "fixed"):
            raise ValueError("component is only used with a fixed displacement")
        return self


class HeatSource(Strict):
    """Heat released inside a region: 'power_density' in W/m3 or total 'power' in W. The region
    may also be a named point ('source' of a point-source shape); then kind is 'power'.
    Total power is that of the whole source, also when only a symmetric half is modelled."""
    region: str
    kind: Literal["power_density", "power"] = "power_density"
    value: float

    v_names = field_validator("region")(lambda cls, v: _name(v))

    @model_validator(mode="before")
    @classmethod
    def _units(cls, data):
        if isinstance(data, dict) and "value" in data and not isinstance(data["value"], float):
            dim = "power" if data.get("kind") == "power" else "power_density"
            data = {**data, "value": to_si(data["value"], dim)}
        return data


class Initial(Strict):
    """Uniform initial values. For head, 'hydrostatic' means p = rho g (head - elevation)."""
    temperature: Temperature | None = None
    head: Length | None = None
    pressure: Pressure | None = None
    concentration: Concentration | None = None


# ---------------------------------------------------------------- mesh and study

class Refinement(Strict):
    """Smaller elements next to a boundary or interface."""
    target: str
    size: Length = Field(gt=0)
    growth: float = Field(default=1.2, ge=1.0, le=2.0)

    v_names = field_validator("target")(lambda cls, v: _name(v))


class MeshSettings(Strict):
    element: Literal["auto", "quad", "tri", "hex"] = "auto"
    size: Length | None = Field(default=None, gt=0)
    divisions: dict[str, int] = Field(default_factory=dict)  # axis or layer name -> number of elements
    refinements: list[Refinement] = Field(default_factory=list, max_length=12)

    @field_validator("divisions")
    @classmethod
    def _div(cls, v):
        out = {}
        for k, n in v.items():
            if not 1 <= int(n) <= 2000:
                raise ValueError(f"divisions for '{k}' must be between 1 and 2000")
            out[_name(k)] = int(n)
        return out


class Study(Strict):
    kind: Literal["steady", "transient"] = "transient"
    end_time: Time | None = Field(default=None, gt=0)
    first_step: Time | None = Field(default=None, gt=0)
    max_step: Time | None = Field(default=None, gt=0)
    growth: float = Field(default=1.0, ge=1.0, le=2.0)
    output_times: list[Time] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _outputs(self):
        if self.end_time is not None and any(t > self.end_time * (1 + 1e-12) or t <= 0 for t in self.output_times):
            raise ValueError("output_times must lie in (0, end_time]")
        return self


class Probe(Strict):
    """A named point or line where results are extracted."""
    name: str
    point: tuple[float, ...] | None = None
    line: tuple[tuple[float, ...], tuple[float, ...]] | None = None
    samples: int = Field(default=101, ge=2, le=2001)

    v_names = field_validator("name")(lambda cls, v: _name(v))

    @model_validator(mode="after")
    def _one(self):
        if (self.point is None) == (self.line is None):
            raise ValueError("a probe has either a point or a line")
        return self


# ---------------------------------------------------------------- model

class Model(Strict):
    schema_version: int = SCHEMA_VERSION
    name: str = "model"
    geometry: Geometry
    materials: dict[str, Material] = Field(default_factory=dict)
    physics: Physics
    boundary_conditions: list[BoundaryCondition] = Field(default_factory=list)
    heat_sources: list[HeatSource] = Field(default_factory=list)
    initial: Initial = Field(default_factory=Initial)
    mesh: MeshSettings = Field(default_factory=MeshSettings)
    study: Study = Field(default_factory=Study)
    probes: list[Probe] = Field(default_factory=list)

    v_names = field_validator("name")(lambda cls, v: _name(v))

    @field_validator("materials")
    @classmethod
    def _mat_names(cls, v):
        return {_name(k): m for k, m in v.items()}

    def content_hash(self) -> str:
        """Hash of everything that changes the computation (the name excluded)."""
        d = self.model_dump(mode="json", exclude={"name"})
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def gravity_on(self) -> bool:
        if self.physics.gravity is not None:
            return self.physics.gravity and vertical_axis(self.geometry) is not None
        # default: on for flow in vertical sections; off for heat alone and for mechanics
        # (gravity with mechanics needs an initial stress state, not in v0.1)
        return vertical_axis(self.geometry) is not None and self.physics.process in ("H", "TH", "HC")
