"""Tools: the only way an agent changes or runs a model.

Each tool has a Pydantic input model (strict-schema friendly: no free-form
dicts, optional fields are nullable) and returns a dict with ok, the payload,
state, a short tree summary and the next step. Tools that do not fit the
current state are hidden; calling one returns the state and what to call.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, ValidationError

from . import configs
from .check import check_model, mesh_hash, tree_summary
from .mesh import MeshError
from .mesh import build_mesh as make_mesh
from .mesh.preview import render
from .post import Results
from .runner import Jobs, RunRecord
from .schema import (BoundaryCondition, Component, HeatSource, Initial, Layer, Material, MeshSettings, Model,
                     Physics, Probe, Refinement, Study, boundaries_of, interfaces_of, regions_of)
from .session import STEPS, Session, friendly_validation
from .translator import TranslationError, translate
from .units import to_si

EXAMPLES = Path(__file__).parent / "examples"
KB = Path(__file__).parent / "agent" / "kb"
MAX_ASKS = 3
JOBS = Jobs()
WAIT = {"run_status": 20.0, "compare": 240.0}  # seconds a call may block; the MCP adapter shortens these


# ================================================================ inputs

class NameValue(BaseModel):
    name: str = Field(description="name of the value")
    value: str = Field(description="value with unit, e.g. '3 W/m/K', '20 degC', '1e-5 m/s', or a plain number")


class NoInput(BaseModel):
    pass


class StartFromExampleIn(BaseModel):
    example_id: str = Field(description="id from list_capabilities, e.g. 'heated_inclusion'")
    changes: list[NameValue] | None = Field(None, description="adjustable values to change, by the names "
                                                               "list_capabilities gives for this example")
    project_name: str | None = Field(None, description="optional project name (letters, digits, _)")


class NewProjectIn(BaseModel):
    name: str = Field(description="project name (letters, digits, _)")


class LayerIn(BaseModel):
    name: str = Field(description="region name, e.g. 'clay'")
    thickness: str = Field(description="thickness with unit, e.g. '10 m'")


class SegmentIn(BaseModel):
    name: str = Field(description="name for this part of the side, e.g. 'salt_source'")
    side: Literal["top", "bottom"]
    start: str = Field(description="x where the part starts, e.g. '150 m'")
    end: str = Field(description="x where the part ends, e.g. '450 m'")


class SetGeometryIn(BaseModel):
    shape: Literal["rect", "rect_inclusion", "axisym_well", "axisym_source", "box"] = Field(
        description="rect: 2D rectangle with horizontal layers; rect_inclusion: 2D rectangle with one circular "
                    "body; axisym_well: radial section around a well; axisym_source: radial section around a heat "
                    "source on the axis (point, or canister with optional buffer); box: 3D block with layers")
    width: str | None = Field(None, description="rect, rect_inclusion: width (x) with unit")
    height: str | None = Field(None, description="rect_inclusion: height (y) with unit")
    layers: list[LayerIn] | None = Field(None, description="rect, axisym_well, box: layers from bottom to top")
    length_x: str | None = Field(None, description="box: length in x")
    length_y: str | None = Field(None, description="box: length in y")
    center_x: str | None = Field(None, description="rect_inclusion: x of the circle centre")
    center_y: str | None = Field(None, description="rect_inclusion: y of the circle centre")
    radius: str | None = Field(None, description="rect_inclusion: circle radius")
    matrix_name: str | None = Field(None, description="rect_inclusion: name of the surrounding region (default matrix)")
    inclusion_name: str | None = Field(None, description="rect_inclusion: name of the circle region (default inclusion)")
    well_radius: str | None = Field(None, description="axisym_well: well radius (> 0)")
    outer_radius: str | None = Field(None, description="axisym_well: outer radius of the model")
    plan_view: bool | None = Field(None, description="rect, rect_inclusion: true for a horizontal plan view (no gravity)")
    segments: list[SegmentIn] | None = Field(None, description="rect: named parts of the top or bottom side that "
                                                                "need their own condition (e.g. a source on part of the top)")
    height_total: str | None = Field(None, description="axisym_source: model height (the upper half when symmetric)")
    symmetric: bool | None = Field(None, description="axisym_source: model only the upper half (default true)")
    source: Literal["point", "canister"] | None = Field(None, description="axisym_source: point source or canister")
    canister_radius: str | None = None
    canister_length: str | None = None
    buffer_radius: str | None = Field(None, description="axisym_source: radius of the buffer-filled hole")
    buffer_length: str | None = Field(None, description="axisym_source: length of the buffer around the canister")


class ComponentIn(BaseModel):
    name: str = Field(description="component name, e.g. 'tracer'")
    pore_diffusion: str = Field(description="pore diffusion coefficient, e.g. '1e-9 m2/s'")
    half_life: str | None = Field(None, description="half-life with unit (radioactive decay), e.g. '30 yr'")
    retardation: str | None = Field(None, description="retardation factor (>= 1)")


class SetPhysicsIn(BaseModel):
    process: Literal["H", "T", "TH", "HC", "HM", "TM", "THM"] = Field(
        description="H: groundwater flow; T: heat conduction; TH: heat carried by groundwater flow; "
                    "HC: solute transport in groundwater flow; HM: flow with deformation (consolidation); "
                    "TM: heat with thermal stress; THM: heat, flow and deformation together")
    gravity: bool | None = Field(None, description="gravity on or off (default: on in vertical sections)")
    component: ComponentIn | None = Field(None, description="HC only: the dissolved component")
    fluid: list[NameValue] | None = Field(None, description="water properties to change: density, viscosity, "
                                                            "specific_heat, thermal_conductivity, thermal_expansion, "
                                                            "density_increase_per_concentration (buoyancy)")


class MaterialIn(BaseModel):
    region: str = Field(description="region name from the geometry")
    library: str | None = Field(None, description="start from a library material (see list_capabilities), e.g. 'granite'")
    values: list[NameValue] = Field(description="properties, e.g. thermal_conductivity '3 W/m/K', porosity '0.2', "
                                                "hydraulic_conductivity '1e-5 m/s', specific_storage '1e-5 1/m', "
                                                "density, specific_heat, solid_density, solid_specific_heat, "
                                                "permeability, longitudinal_dispersivity, transverse_dispersivity, label")


class SetMaterialsIn(BaseModel):
    materials: list[MaterialIn]


class ConditionIn(BaseModel):
    boundary: str = Field(description="boundary name, e.g. 'left', 'top', 'well'")
    variable: Literal["head", "pressure", "temperature", "concentration", "displacement"]
    kind: Literal["fixed", "flux", "rate", "roller", "load"] = Field(
        description="fixed value; flux per area (inflow positive); rate = total over the boundary (m3/s or W); "
                    "displacement only: roller (no movement across the boundary), load (normal pressure, "
                    "compression positive), fixed (with component)")
    value: str | None = Field(None, description="value with unit, e.g. '25 degC', '10 m', '-0.01 m3/s', '2 MPa'; "
                                                "not needed for a roller")
    component: Literal["x", "y", "z", "r"] | None = Field(None, description="fixed displacement only: which component")


class HeatSourceIn(BaseModel):
    region: str
    kind: Literal["power_density", "power"] = Field(description="power_density in W/m3, or total power in W "
                                                                "(per metre of thickness in 2D)")
    value: str


class SetConditionsIn(BaseModel):
    boundary_conditions: list[ConditionIn] | None = Field(None, description="added or replacing the same boundary and variable")
    initial: list[NameValue] | None = Field(None, description="initial values: temperature, head, pressure, concentration")
    heat_sources: list[HeatSourceIn] | None = None
    remove_boundaries: list[str] | None = Field(None, description="boundaries whose conditions are removed")


class RefinementIn(BaseModel):
    target: str = Field(description="boundary, interface or region to refine")
    size: str = Field(description="element size there, e.g. '0.1 m'")
    growth: float | None = Field(None, description="size growth per element away from it (1.05 to 1.5, default 1.2)")


class DivisionIn(BaseModel):
    name: str = Field(description="axis (x, y, z, r) or layer name")
    elements: int


class SetMeshIn(BaseModel):
    size: str | None = Field(None, description="general element size, e.g. '2 m'")
    element: Literal["auto", "quad", "tri", "hex"] | None = None
    divisions: list[DivisionIn] | None = Field(None, description="number of elements along an axis or across a layer")
    refinements: list[RefinementIn] | None = Field(None, description="replaces the refinement list")


class ShowMeshIn(BaseModel):
    zoom: list[float] | None = Field(None, description="optional [xmin, xmax, ymin, ymax] in m")


class SetStudyIn(BaseModel):
    kind: Literal["steady", "transient"]
    end_time: str | None = Field(None, description="transient: end time, e.g. '10 yr'")
    first_step: str | None = Field(None, description="first time step, e.g. '1 d'")
    growth: float | None = Field(None, description="time step growth factor (1 to 2)")
    max_step: str | None = Field(None, description="largest time step")
    output_times: list[str] | None = Field(None, description="extra output times, e.g. ['1 yr', '5 yr']")


class ShowResultsIn(BaseModel):
    field: str = Field(description="temperature, head, pressure, darcy_velocity, heat_flux, displacement, sigma "
                                   "(stress, tension positive) or the component name")
    component: str | None = Field(None, description="vectors: x, y (r, z); stress: xx, yy, zz, xy (rr, zz, tt, rz); "
                                                    "default: magnitude")
    kind: Literal["map", "profile", "series"]
    time: str | None = Field(None, description="map/profile: output time (default: last)")
    probe: str | None = Field(None, description="name of a probe from show_model")
    point: list[float] | None = Field(None, description="series: point coordinates in m")
    line: list[list[float]] | None = Field(None, description="profile: [[x1, y1], [x2, y2]] in m")


class CompareIn(BaseModel):
    comparison: str = Field(description="same_settings, no_solid_thermal_expansion, no_water_thermal_expansion, "
                                        "no_hydro_mechanical_coupling, no_sorption, no_decay or half_element_size")
    field: str = Field(description="quantity to compare, e.g. temperature, pressure, displacement, sigma, head")
    component: str | None = Field(None, description="vector or stress component (see show_results)")
    probe: str | None = Field(None, description="a point or line probe from show_model")
    time: str | None = Field(None, description="output time (default: last)")


class CardItemIn(BaseModel):
    label: str = Field(description="short name of the number, e.g. 'peak canister temperature'")
    kind: Literal["value", "change", "max", "min", "mean", "comparison"] = Field(
        description="value at a point; change = value minus the initial value at that point (a rise or drop); "
                    "max/min/mean along a line probe or over the model; comparison = largest difference of a compare")
    field: str | None = Field(None, description="temperature, pressure, head, displacement, sigma, ...")
    component: str | None = None
    probe: str | None = Field(None, description="point probe (value) or line probe (max/min/mean); none = whole model")
    point: list[float] | None = None
    time: str | None = Field(None, description="output time (default: last)")
    comparison: str | None = Field(None, description="comparison name, for kind 'comparison'")


class AnswerCardIn(BaseModel):
    items: list[CardItemIn] = Field(description="the numbers to report (1 to 12)")


class GoToStepIn(BaseModel):
    step: Literal["geometry", "physics", "materials", "conditions", "mesh", "study"]


class AskUserIn(BaseModel):
    question: str = Field(description="one short question")
    default: str = Field(description="the value used if the user does not answer")


# ================================================================ helpers

def _err(msg, fix="", **extra):
    return {"ok": False, "error": msg, "fix": fix, **extra}


def _q(text: str | None, dim: str):
    return None if text is None else to_si(text, dim)


def _set_path(d: dict, path: str, value):
    """Set a value in a model dict. Lists are addressed by name/boundary(.variable)/region."""
    parts = path.split(".")
    cur = d
    i = 0
    while i < len(parts) - 1:
        key = parts[i]
        nxt = cur[key] if isinstance(cur, dict) else None
        if isinstance(nxt, list):
            sel = parts[i + 1]
            if key == "boundary_conditions":
                var = parts[i + 2]
                fam = ("head", "pressure") if var in ("head", "pressure") else (var,)
                items = [x for x in nxt if x["boundary"] == sel and x["variable"] in fam]
                i += 1
            else:
                items = [x for x in nxt if x.get("name") == sel or x.get("region") == sel]
            if not items:
                raise KeyError(f"nothing named '{sel}' under {key}")
            cur = items[0]
            i += 2
            continue
        cur = nxt
        i += 1
        if cur is None:
            raise KeyError(f"no '{key}' in the model")
    cur[parts[-1]] = value


def library() -> dict:
    return json.loads((KB / "materials.json").read_text())["materials"]


class SearchKbIn(BaseModel):
    query: str = Field(description="what to look up, e.g. 'bentonite thermal conductivity' or 'Peclet number'")


def search_kb(s: Session, a: SearchKbIn):
    """Look up material values (with sources and conditions), physics notes and resolution rules."""
    words = [w for w in a.query.lower().replace(",", " ").split() if len(w) > 2]
    hits = []
    for name, m in library().items():
        text = (name + " " + m["title"] + " " + json.dumps(m)).lower()
        score = sum(text.count(w) for w in words)
        if score:
            srcs = json.loads((KB / "materials.json").read_text())["_sources"]
            hits.append((score, {"material": name, "title": m["title"], "values": m["values"], "ranges": m["ranges"],
                                 "conditions": m["conditions"], "sources": [srcs[k] for k in m["sources"]]}))
    for f in sorted(KB.glob("*.md")):
        for block in f.read_text().split("\n## "):
            score = sum(block.lower().count(w) for w in words)
            if score:
                hits.append((score, {"note": f.stem, "text": block.strip()[:1200]}))
    hits.sort(key=lambda x: -x[0])
    return {"ok": True, "results": [h for _, h in hits[:3]] or [{"note": "nothing found"}]}


def _example(eid: str) -> dict:
    p = EXAMPLES / f"{eid}.json"
    if not p.exists():
        raise KeyError(eid)
    return json.loads(p.read_text())


def _examples() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(EXAMPLES.glob("*.json"))]


# ================================================================ tools

def list_capabilities(s: Session, a: NoInput):
    """What this version can compute: verified configurations and examples with their adjustable values."""
    exs = [{"id": e["id"], "title": e["title"], "title_ko": e.get("title_ko"), "configuration": e["configuration"],
            "description": e["description"], "adjustable": sorted(e["adjustable"])} for e in _examples()]
    cfg = [{"id": c.id, "process": c.process, "shapes": list(c.shapes), "title": c.title,
            "verified_by": list(c.cases), "steady": c.steady} for c in configs.CONFIGURATIONS]
    mats = {k: v["title"] for k, v in library().items()}
    return {"ok": True, "configurations": cfg, "examples": exs, "material_library": mats,
            "not_included": "reactive chemistry, two-phase or unsaturated flow, fractures, freezing, plasticity, "
                            "mechanics in this preview step, large or site-specific models. " + configs.CONTACT}


def start_from_example(s: Session, a: StartFromExampleIn):
    """Load a verified example and apply changes. Fast path: then build_mesh, check_model, run."""
    try:
        ex = _example(a.example_id)
    except KeyError:
        ids = [e["id"] for e in _examples()]
        return _err(f"unknown example '{a.example_id}'", f"use one of: {', '.join(ids)}")
    d = json.loads(json.dumps(ex["model"]))
    applied = []
    for nv in a.changes or []:
        path = ex["adjustable"].get(nv.name, {}).get("path")
        if path is None:
            return _err(f"'{nv.name}' is not adjustable in this example",
                        f"adjustable: {', '.join(sorted(ex['adjustable']))}; other changes: use go_to_step and set_*")
        try:
            _set_path(d, path, nv.value)
        except KeyError as e:
            return _err(f"cannot change '{nv.name}': {e}")
        applied.append(f"{nv.name} = {nv.value}")
    if a.project_name:
        d["name"] = a.project_name
    st = d.get("study", {})
    if st.get("end_time") is not None and st.get("output_times"):
        end = to_si(st["end_time"], "time")
        keep = [t for t in st["output_times"] if to_si(t, "time") < end]
        if len(keep) < len(st["output_times"]):
            applied.append(f"example output times after the new end time removed: "
                           f"{[t for t in st['output_times'] if t not in keep]}")
            st["output_times"] = keep
    try:
        model = Model.model_validate(d)
    except ValidationError as e:
        return _err("the changed example is not valid", "correct the values", details=friendly_validation(e))
    s.example = ex["id"]
    s.load_model(model)
    s.mesh = None
    return {"ok": True, "example": ex["id"], "title": ex["title"], "configuration": ex["configuration"],
            "changes_applied": applied, "verified_by": ex["verification_cases"]}


def new_project(s: Session, a: NewProjectIn):
    """Start an empty model. Next: set_geometry."""
    from .schema import _name
    try:
        name = _name(a.name)
    except ValueError as e:
        return _err(str(e))
    s.__init__(root=s.root, name=name)
    s.state, s.focus = "DRAFT", "geometry"
    return {"ok": True, "project": name}


def set_geometry(s: Session, a: SetGeometryIn):
    """Define the shape and its regions (layers or a circular body). Next: set_physics."""
    try:
        if a.shape in ("rect", "axisym_well", "box"):
            if not a.layers:
                return _err(f"shape '{a.shape}' needs layers", "give layers from bottom to top, e.g. [{name: 'rock', thickness: '50 m'}]")
            layers = [Layer(name=l.name, thickness=l.thickness) for l in a.layers]
        if a.shape == "rect":
            g = {"kind": "rect", "width": a.width, "layers": layers,
                 "plane": "horizontal" if a.plan_view else "vertical",
                 "segments": [sg.model_dump() for sg in a.segments or []]}
        elif a.shape == "rect_inclusion":
            g = {"kind": "rect_inclusion", "width": a.width, "height": a.height, "center": (a.center_x, a.center_y),
                 "radius": a.radius, "matrix": a.matrix_name or "matrix", "inclusion": a.inclusion_name or "inclusion",
                 "plane": "horizontal" if a.plan_view else "vertical"}
        elif a.shape == "axisym_well":
            g = {"kind": "axisym_well", "well_radius": a.well_radius, "outer_radius": a.outer_radius, "layers": layers}
        elif a.shape == "axisym_source":
            g = {"kind": "axisym_source", "outer_radius": a.outer_radius, "height": a.height_total,
                 "symmetric": True if a.symmetric is None else a.symmetric, "source": a.source or "point",
                 "canister_radius": a.canister_radius, "canister_length": a.canister_length,
                 "buffer_radius": a.buffer_radius, "buffer_length": a.buffer_length}
        else:
            g = {"kind": "box", "length_x": a.length_x, "length_y": a.length_y, "layers": layers}
        from pydantic import TypeAdapter
        from .schema import Geometry
        geom = TypeAdapter(Geometry).validate_python(g)
    except ValidationError as e:
        return _err("the geometry is not valid", "correct the listed values", details=friendly_validation(e))
    old_b = set(boundaries_of(s.geometry)) if s.geometry else set()
    s.geometry = geom
    regions, bnames = regions_of(geom), boundaries_of(geom)
    dropped = [r for r in s.materials if r not in regions]
    for r in dropped:
        del s.materials[r]
    lost = [bc.boundary for bc in s.boundary_conditions if bc.boundary not in bnames]
    s.boundary_conditions = [bc for bc in s.boundary_conditions if bc.boundary in bnames]
    s.heat_sources = [h for h in s.heat_sources if h.region in regions]
    s.changed()
    out = {"ok": True, "regions": regions, "boundaries": bnames, "interfaces": interfaces_of(geom)}
    if s.probes:
        out["probes"] = {p.name: (p.point or p.line) for p in s.probes}
        out["probe_note"] = "probes keep their coordinates; check them after changing the shape"
    from .schema import points_of
    if points_of(geom):
        out["points"] = points_of(geom)
    if dropped or lost:
        out["removed"] = {"materials_of": dropped, "conditions_on": sorted(set(lost))}
    return out


def set_physics(s: Session, a: SetPhysicsIn):
    """Choose the physics. Next: set_materials (the result lists the properties each region needs)."""
    from .check import NEEDS
    comps = []
    try:
        if a.component:
            c = a.component
            comps = [Component(name=c.name, pore_diffusion=c.pore_diffusion, half_life=c.half_life,
                               retardation=float(c.retardation) if c.retardation else 1.0)]
        fluid = {nv.name.strip().lower(): nv.value for nv in a.fluid or []}
        phys = Physics(process=a.process, gravity=a.gravity, components=comps, **({"fluid": fluid} if fluid else {}))
    except (ValidationError, ValueError) as e:
        det = friendly_validation(e) if isinstance(e, ValidationError) else [{"message": str(e)}]
        return _err("the physics settings are not valid", "correct the listed values", details=det)
    if a.process == "HC" and not comps:
        return _err("transport (HC) needs a component", "give component {name, pore_diffusion, half_life?, retardation?}")
    s.physics = phys
    s.changed()
    shapes = configs.supported_shapes(a.process)
    out = {"ok": True, "process": a.process, "material_properties_needed": list(NEEDS[a.process]),
           "verified_shapes": shapes}
    if a.process == "T":
        out["material_properties_needed"] += ["density and specific_heat (transient)"]
    if a.process == "H":
        out["material_properties_needed"] += ["specific_storage (transient)"]
    if s.geometry is not None and s.geometry.kind not in shapes:
        out["warning"] = f"shape '{s.geometry.kind}' is not verified for {a.process}. {configs.CONTACT}"
    return out


MATERIAL_FIELDS = {"permeability": "permeability", "hydraulic_conductivity": "velocity", "porosity": "dimensionless",
                   "specific_storage": "specific_storage", "thermal_conductivity": "thermal_conductivity",
                   "solid_density": "density", "solid_specific_heat": "specific_heat", "density": "density",
                   "specific_heat": "specific_heat", "longitudinal_dispersivity": "length",
                   "transverse_dispersivity": "length", "youngs_modulus": "pressure", "poissons_ratio": "dimensionless",
                   "biot_coefficient": "dimensionless", "thermal_expansion": "linear_expansion"}


def set_materials(s: Session, a: SetMaterialsIn):
    """Give material properties per region (values with units). Next: set_conditions."""
    if s.geometry is None:
        return _err("define the geometry first", "use go_to_step('geometry')")
    regions = regions_of(s.geometry)
    done = []
    for mi in a.materials:
        r = mi.region.strip().lower()
        if r not in regions:
            import difflib
            m = difflib.get_close_matches(r, regions, n=1)
            return _err(f"region '{mi.region}' does not exist (regions: {', '.join(regions)})",
                        f"did you mean '{m[0]}'?" if m else "use a listed region name")
        cur = (s.materials.get(r) or Material()).model_dump(exclude_none=True)
        if mi.library:
            lib = library().get(mi.library.strip().lower())
            if lib is None:
                return _err(f"no library material '{mi.library}'", f"use one of: {', '.join(library())}")
            cur = {k: v for k, v in lib["values"].items() if k in MATERIAL_FIELDS}
            cur["label"] = f"{lib['title']} (library values)"
        for nv in mi.values:
            key = nv.name.strip().lower()
            if key == "label":
                cur["label"] = nv.value
                continue
            if key not in MATERIAL_FIELDS:
                return _err(f"unknown property '{nv.name}'", f"use one of: {', '.join(MATERIAL_FIELDS)}")
            cur[key] = nv.value
            if key == "permeability":
                cur.pop("hydraulic_conductivity", None)
            if key == "hydraulic_conductivity":
                cur.pop("permeability", None)
        try:
            s.materials[r] = Material.model_validate(cur)
        except ValidationError as e:
            return _err(f"region '{r}': invalid values", "correct the listed values", details=friendly_validation(e))
        done.append(r)
    s.changed()
    missing = [r for r in regions if r not in s.materials]
    return {"ok": True, "updated": done, "regions_without_material": missing}


def set_conditions(s: Session, a: SetConditionsIn):
    """Boundary conditions, initial values and heat sources. Next: set_mesh / build_mesh."""
    if s.geometry is None:
        return _err("define the geometry first", "use go_to_step('geometry')")
    from .schema import points_of
    bnames = boundaries_of(s.geometry) + [q for q in points_of(s.geometry) if q != "source"]
    if a.remove_boundaries:
        s.boundary_conditions = [bc for bc in s.boundary_conditions if bc.boundary not in a.remove_boundaries]
    for ci in a.boundary_conditions or []:
        b = ci.boundary.strip().lower()
        if b not in bnames:
            import difflib
            m = difflib.get_close_matches(b, bnames, n=1)
            hint = "interfaces are for extracting values only" if b in interfaces_of(s.geometry) else (
                f"did you mean '{m[0]}'?" if m else "")
            return _err(f"boundary '{ci.boundary}' does not exist (boundaries: {', '.join(bnames)})", hint)
        if ci.value is None and ci.kind != "roller":
            return _err(f"condition on '{b}' needs a value", "give value with unit")
        try:
            bc = BoundaryCondition(boundary=b, variable=ci.variable, kind=ci.kind,
                                   value=ci.value if ci.value is not None else 0.0, component=ci.component)
        except ValidationError as e:
            return _err(f"condition on '{b}' is not valid", "check the value and its unit", details=friendly_validation(e))
        fam = lambda v: "water" if v in ("head", "pressure") else v
        same = (lambda x: x.boundary == b and fam(x.variable) == fam(bc.variable)
                and (bc.variable != "displacement" or (x.kind == bc.kind and x.component == bc.component)))
        s.boundary_conditions = [x for x in s.boundary_conditions if not same(x)] + [bc]
    if a.initial:
        cur = s.initial.model_dump(exclude_none=True)
        for nv in a.initial:
            k = nv.name.strip().lower()
            if k not in ("temperature", "head", "pressure", "concentration"):
                return _err(f"unknown initial value '{nv.name}'", "use temperature, head, pressure or concentration")
            cur[k] = nv.value
            if k == "head":
                cur.pop("pressure", None)
            if k == "pressure":
                cur.pop("head", None)
        try:
            s.initial = Initial.model_validate(cur)
        except ValidationError as e:
            return _err("initial values are not valid", "check the units", details=friendly_validation(e))
    for hi in a.heat_sources or []:
        try:
            hs = HeatSource(region=hi.region, kind=hi.kind, value=hi.value)
        except ValidationError as e:
            return _err("heat source is not valid", "check the value and its unit", details=friendly_validation(e))
        from .schema import points_of
        names = regions_of(s.geometry) + points_of(s.geometry)
        if hs.region not in names:
            return _err(f"region '{hi.region}' does not exist (regions and points: {', '.join(names)})")
        s.heat_sources = [h for h in s.heat_sources if h.region != hs.region] + [hs]
    s.changed()
    return {"ok": True, "boundary_conditions": [bc.model_dump(exclude_none=True) for bc in s.boundary_conditions],
            "initial": s.initial.model_dump(exclude_none=True),
            "heat_sources": [h.model_dump() for h in s.heat_sources],
            "boundaries_without_condition": [b for b in bnames if b not in {bc.boundary for bc in s.boundary_conditions}
                                             and "_" not in b] or None,
            "note": "boundaries without a condition are closed (no flow, no heat flux)"}


def set_mesh(s: Session, a: SetMeshIn):
    """Mesh settings: general size, element shape, divisions, local refinements. Next: build_mesh."""
    cur = s.mesh_settings.model_dump()
    if a.size is not None:
        cur["size"] = a.size
    if a.element is not None:
        cur["element"] = a.element
    if a.divisions is not None:
        cur["divisions"] = {d.name: d.elements for d in a.divisions}
    if a.refinements is not None:
        cur["refinements"] = [{"target": r.target, "size": r.size, "growth": r.growth or 1.2} for r in a.refinements]
    try:
        s.mesh_settings = MeshSettings.model_validate(cur)
    except ValidationError as e:
        return _err("mesh settings are not valid", "correct the listed values", details=friendly_validation(e))
    s.changed()
    return {"ok": True, "mesh_settings": s.mesh_settings.model_dump(exclude_none=True)}


def build_mesh(s: Session, a: NoInput):
    """Generate the mesh and check its quality. Returns counts, quality warnings and a preview picture."""
    m = s.model
    if m is None:
        return _err("geometry and physics are needed before meshing", "use go_to_step('geometry')")
    d = s.dir / "build"
    try:
        bundle, rep = make_mesh(m, d)
    except MeshError as e:
        return _err(str(e), "change the mesh settings with set_mesh")
    pic = render(bundle, s.dir / "mesh.png")
    bsizes = {}
    for name, b in bundle.boundaries.items():
        ids = np.asarray(b.cell_data["bulk_element_ids"]).astype(int)
        sz = bundle.bulk.compute_cell_sizes(length=False, area=bundle.dim == 2, volume=bundle.dim == 3)
        key = "Area" if bundle.dim == 2 else "Volume"
        meas = np.abs(np.asarray(sz.cell_data[key]))[ids]
        bsizes[name] = float(np.max(meas ** (1 / bundle.dim)))
    s.mesh = {"hash": mesh_hash(m), "summary": bundle.summary(), "report": rep.as_dict(), "bundle": bundle,
              "dir": str(d), "preview": str(pic), "boundary_sizes": bsizes,
              "size_max": rep.stats.get("element_size_max")}
    s.check = None
    nxt = s.next_step()
    s.focus = nxt if nxt != "check" else "mesh"  # stay on the mesh step so it can be adjusted
    st = rep.stats
    return {"ok": rep.ok, "elements": st["elements"], "nodes": st["nodes"], "element_type": st["element_type"],
            "element_order": bundle.order, "engine": bundle.engine,
            "element_size_range_m": [round(st["element_size_min"], 6), round(st["element_size_max"], 6)],
            "quality_issues": [i.as_dict() for i in rep.issues], "preview": str(pic)}


def show_mesh(s: Session, a: ShowMeshIn):
    """Picture of the mesh with regions in colour and named boundaries; optional zoom."""
    if not s.mesh:
        return _err("the mesh is not built", "use build_mesh")
    p = render(s.mesh["bundle"], s.dir / ("mesh_zoom.png" if a.zoom else "mesh.png"),
               zoom=tuple(a.zoom) if a.zoom and len(a.zoom) == 4 else None)
    return {"ok": True, "picture": str(p), "summary": s.mesh["summary"]}


def set_study(s: Session, a: SetStudyIn):
    """Steady or transient study, time steps and output times. Next: check_model."""
    try:
        st = Study(kind=a.kind, end_time=a.end_time, first_step=a.first_step, growth=a.growth or 1.0,
                   max_step=a.max_step, output_times=a.output_times or [])
    except ValidationError as e:
        return _err("study settings are not valid", "correct the listed values", details=friendly_validation(e))
    if st.kind == "transient" and st.end_time is None:
        return _err("a transient study needs end_time", "give end_time, e.g. '10 yr'")
    s.study = st
    s.changed()
    from .translator import time_steps
    m = s.model
    dts, outs = time_steps(m)
    return {"ok": True, "steps": len(dts), "first_step_s": dts[0], "largest_step_s": max(dts),
            "output_times_s": outs}


def check_model_tool(s: Session, a: NoInput):
    """Check completeness, support, units and mesh. If ok the model can run."""
    m = s.model
    if m is None:
        return _err("geometry and physics are missing", "use go_to_step('geometry')")
    rep = check_model(m, s.mesh)
    if s.study is None:  # the session shows a placeholder study until set_study is called
        rep["issues"].insert(0, {"level": "error", "code": "study_not_set", "message": "the study is not set",
                                 "fix": "use set_study (steady, or transient with end_time)"})
        rep["ok"] = False
    s.check = {"hash": m.content_hash(), "report": rep}
    if rep["ok"]:
        s.state = "CHECKED"
        s.save()
    else:
        errs = [i for i in rep["issues"] if i["level"] == "error"]
        first = errs[0]["code"] if errs else ""
        step = ("mesh" if first.startswith("mesh") else "materials" if "material" in first or "property" in first
                else "conditions" if "condition" in first or "initial" in first or "boundary" in first
                else "study" if "step" in first or "end_time" in first else s.next_step())
        s.focus = step if step in STEPS else s.focus
    return {"ok": rep["ok"], **rep}


def show_model(s: Session, a: NoInput):
    """The whole model tree (SI units, temperature in K) and the probes for results."""
    m = s.model
    if m is None:
        return {"ok": True, "model": None}
    return {"ok": True, "model": m.model_dump(mode="json", exclude_none=True),
            "probes": [p.name for p in m.probes], "mesh": s.mesh["summary"] if s.mesh else None}


def run(s: Session, a: NoInput):
    """Start the computation. Returns a job id at once; then call run_status."""
    m = s.model
    h = m.content_hash()
    if not s.check or s.check["hash"] != h or not s.check["report"]["ok"]:
        return _err("the current model has not passed check_model", "call check_model")
    if h in s.results and s.results[h]["status"] == "succeeded":
        s.state = "COMPUTED"
        s.job = {"id": s.results[h]["run_id"], "hash": h}
        return {"ok": True, "cached": True, "job_id": s.results[h]["run_id"],
                "note": "this exact model was computed before; the stored result is used"}
    builddir = s.dir / "runs" / h / "build"
    try:
        bundle = s.mesh["bundle"]
        bundle.write(builddir)
        br = translate(m, bundle, builddir)
    except TranslationError as e:
        return _err(f"translation failed: {e}", "report this; check_model should have caught it")
    (builddir / "translation.log").write_text("\n".join(br.log))

    def done(rec: RunRecord):
        s.results[h] = rec.as_dict()

    jid = JOBS.submit(br.prj, s.dir / "runs" / h / "out", br.t_end, on_done=done,
                      expected_fields=br.primary, output_times=br.output_times)
    s.job = {"id": jid, "hash": h, "translation": br.log}
    s.state = "RUNNING"
    return {"ok": True, "job_id": jid, "translation_notes": br.log}


def run_status(s: Session, a: NoInput):
    """Progress of the current run. When finished: next show_results."""
    if not s.job:
        return _err("nothing is running", "call run")
    rec = JOBS.status(s.job["id"]) if s.job["id"] in JOBS._jobs else None
    if rec is None:
        r = s.results.get(s.job["hash"])
        return {"ok": True, "status": r["status"] if r else "unknown"}
    if rec.status in ("queued", "running"):
        JOBS.wait(s.job["id"], timeout=WAIT["run_status"])
    if rec.status == "succeeded":
        s.results[s.job["hash"]] = rec.as_dict()
        s.state = "COMPUTED"
        return {"ok": True, "status": "succeeded", "seconds": rec.seconds,
                "output_times_s": [t for t, _ in rec.outputs],
                "checks": {"reached_end_time": rec.reached_end, "finite_values": rec.finite},
                **({"notes": rec.notes} if rec.notes else {})}
    if rec.status == "failed":
        s.state = "DRAFT"
        f = rec.failure or {}
        s.focus = "study" if f.get("code") in ("nonconvergence", "timeout") else "mesh" if f.get("code") == "jacobian" else s.focus
        return {"ok": False, "status": "failed", "failure": f, "fix": f.get("fix", "")}
    return {"ok": True, "status": rec.status, "progress": round(rec.progress, 3), "seconds": round(rec.seconds, 1)}


def show_results(s: Session, a: ShowResultsIn):
    """Figures and numbers: a field map, a profile along a line, or a time series at a point."""
    from . import figures
    m = s.model
    r = s.results.get(m.content_hash())
    if not r or r["status"] != "succeeded":
        return _err("no result for the current model", "call run")
    res = Results.load(Path(r["rundir"]), m)
    t = res.times[-1] if a.time is None else output_time(res.times, to_si(a.time, "time"))
    figdir = s.dir / "figures" / r["run_id"]
    figdir.mkdir(parents=True, exist_ok=True)
    if a.component:
        res.select_component(a.field, a.component)
    probes = {p.name: p for p in m.probes}
    try:
        if a.kind == "map":
            p = figures.field_map(res, a.field, t, figdir / f"map_{a.field}_{t:g}.png")
            v = res.field(res.mesh_at(t), a.field)
            vv = np.linalg.norm(v, axis=1) if v.ndim == 2 else v
            return {"ok": True, "picture": str(p), "time_s": t, "min": float(vv.min()), "max": float(vv.max())}
        if a.kind == "profile":
            ln = a.line or (probes[a.probe].line if a.probe in probes and probes[a.probe].line else None)
            if ln is None:
                return _err("a profile needs a line or a line probe", f"probes: {', '.join(probes) or 'none'}")
            times = [t] if a.time else list(res.times[1:])
            p, data = figures.profile(res, a.field, times, ln[0], ln[1], figdir / f"profile_{a.field}.png")
            return {"ok": True, "picture": str(p), "values": data}
        pt = a.point or (probes[a.probe].point if a.probe in probes and probes[a.probe].point else None)
        if pt is None:
            return _err("a series needs a point or a point probe", f"probes: {', '.join(probes) or 'none'}")
        p, data = figures.series(res, a.field, pt, figdir / f"series_{a.field}.png")
        return {"ok": True, "picture": str(p), "values": data}
    except (KeyError, ValueError) as e:
        return _err(str(e), "check the field name, time and coordinates")


def _run_variant(s: Session, vm: Model, rebuild_mesh: bool, wait: float, fresh: bool = False):
    """Run a variant of the current model (cached by its hash; fresh=True runs again in its own folder).
    Returns the run record dict, or None while it is still running."""
    h = vm.content_hash() + ("_rerun" if fresh else "")
    if h in s.results and s.results[h]["status"] == "succeeded":
        return s.results[h]
    builddir = s.dir / "runs" / h / "build"
    if rebuild_mesh:
        bundle, rep = make_mesh(vm, builddir)
        if not rep.ok:
            raise ValueError("the finer mesh failed its checks: " + "; ".join(i.message for i in rep.issues))
    else:
        bundle = s.mesh["bundle"]
        bundle.write(builddir)
    br = translate(vm, bundle, builddir)

    def done(rec: RunRecord):
        s.results[h] = rec.as_dict()

    key = f"variant:{h}"
    if key not in s.notes:
        jid = JOBS.submit(br.prj, s.dir / "runs" / h / "out", br.t_end, on_done=done,
                      expected_fields=br.primary, output_times=br.output_times)
        s.notes.append(key)
        s.notes.append(f"job:{h}:{jid}")
    jid = [n.split(":")[2] for n in s.notes if n.startswith(f"job:{h}:")][-1]
    rec = JOBS.wait(jid, timeout=wait)
    if rec.status == "succeeded":
        s.results[h] = rec.as_dict()
        return s.results[h]
    if rec.status == "failed":
        raise ValueError(f"the comparison run failed: {rec.failure}")
    return None


def compare(s: Session, a: CompareIn):
    """Run the model again with one named change and report the difference at a probe. The base result must exist."""
    from . import compare as cmp
    from . import figures
    m = s.model
    base = s.results.get(m.content_hash())
    if not base or base["status"] != "succeeded":
        return _err("no result for the current model", "call run first")
    try:
        vm = cmp.variant(m, a.comparison)
    except (KeyError, ValueError) as e:
        return _err(str(e))
    rec = _run_variant(s, vm, cmp.changes_mesh(a.comparison), wait=WAIT["compare"], fresh=a.comparison == "same_settings")
    if rec is None:
        return {"ok": True, "status": "running", "note": "the comparison run is still going; call compare again with the same input"}
    r0, r1 = Results.load(Path(base["rundir"]), m), Results.load(Path(rec["rundir"]), vm)
    t = r0.times[-1] if a.time is None else output_time(r0.times, to_si(a.time, "time"))
    probes = {p.name: p for p in m.probes}
    pr = probes.get(a.probe) if a.probe else next(iter(probes.values()), None)
    if pr is None:
        return _err("a probe is needed", "add probes, or give probe from show_model")
    if a.component:
        r0.select_component(a.field, a.component)
        r1.select_component(a.field, a.component)
    if pr.line:
        pts = np.linspace(np.asarray(pr.line[0], float), np.asarray(pr.line[1], float), 41)
    else:
        pts = np.atleast_2d(np.asarray(pr.point, float))
    v0 = r0.at_points(t, a.field, pts)
    v1 = r1.at_points(output_time(r1.times, t), a.field, pts)
    if v0.ndim == 2:
        v0, v1 = np.linalg.norm(v0, axis=1), np.linalg.norm(v1, axis=1)
    d = v1 - v0
    scale = max(float(np.max(np.abs(v0 - (m.initial.temperature if a.field == "temperature" else 0.0)))), 1e-300)
    rel = float(np.max(np.abs(d)) / scale)
    noise = rel < 1e-6
    out = {"ok": True, "comparison": a.comparison, "changed": cmp.COMPARISONS[a.comparison]["changes"],
           "kept": "process, mesh, conditions, time steps and all other values" if not cmp.changes_mesh(a.comparison)
           else "process, conditions, time steps and all material values",
           "field": a.field + (f" ({a.component})" if a.component else ""), "time_s": t, "probe": pr.name,
           "max_abs_difference": float(np.max(np.abs(d))), "max_relative_difference": rel,
           "difference_is_numerical_noise": noise, "base_run_id": base["run_id"]}
    if pr.line:
        k = np.linspace(0, len(d) - 1, 11).round().astype(int)
        out["base_values"], out["variant_values"] = v0[k].tolist(), v1[k].tolist()
        out["distance_m"] = np.linalg.norm(pts[k] - pts[0], axis=1).round(6).tolist()
    else:
        out["base_value"], out["variant_value"] = float(v0[0]), float(v1[0])
    if a.comparison == "same_settings":
        out["note"] = "identical models give identical results" if noise else "WARNING: identical models differ; report this"
    s.compares[a.comparison] = out
    return out


def answer_card(s: Session, a: AnswerCardIn):
    """Compute the numbers to report and the results page. Quote only numbers from this card."""
    from . import figures, report
    m = s.model
    rec = s.results.get(m.content_hash())
    if not rec or rec["status"] != "succeeded":
        return _err("no result for the current model", "call run")
    if not 1 <= len(a.items) <= 12:
        return _err("give 1 to 12 items")
    items = []
    for it in a.items:
        d = it.model_dump()
        d["time_s"] = to_si(it.time, "time") if it.time else None
        if it.kind != "comparison" and not it.field:
            return _err(f"item '{it.label}' needs a field")
        items.append(d)
    try:
        card = report.make_card(m, rec, items,
                                {k: v for k, v in s.compares.items() if v.get("base_run_id") == rec["run_id"]})
    except (KeyError, ValueError) as e:
        return _err(str(e), "check probes, fields and times with show_model")
    s.cards.append(card)
    (s.dir / "cards.json").write_text(json.dumps(s.cards, indent=1, default=str, ensure_ascii=False))
    (s.dir / "seen_numbers.json").write_text(json.dumps(sorted(s.seen_numbers)))
    s.save()
    figdir = s.dir / "figures" / rec["run_id"]
    figs = sorted(figdir.glob("*.png")) if figdir.exists() else []
    if not figs:
        res = Results.load(Path(rec["rundir"]), m)
        main = {"T": "temperature", "TH": "temperature", "TM": "temperature", "THM": "temperature",
                "H": "head", "HC": m.physics.components[0].name if m.physics.components else "pressure",
                "HM": "pressure"}[m.physics.process]
        figdir.mkdir(parents=True, exist_ok=True)
        figs = [figures.field_map(res, main, res.times[-1], figdir / f"map_{main}.png")]
    res = Results.load(Path(rec["rundir"]), m)
    main = {"T": "temperature", "TH": "temperature", "TM": "temperature", "THM": "temperature",
            "H": "head", "HC": m.physics.components[0].name if m.physics.components else "pressure",
            "HM": "pressure"}[m.physics.process]
    view = report.viewer(res, main, res.times[-1], s.dir / "viewer.html")
    page = report.results_page(m, card, figs, s.dir / "report.html", viewer=view,
                               translation=(s.job or {}).get("translation"))
    s.state = "REPORTED"
    return {"ok": True, "card": card["table"], "results_page": str(page),
            "rule": "the answer may quote only numbers from this card or from the user's inputs"}


def go_to_step(s: Session, a: GoToStepIn):
    """Open a step to change it (shows that step's tools). Changes send the model back to DRAFT."""
    s.focus = a.step
    if s.state in ("CHECKED", "COMPUTED", "REPORTED"):
        s.state = "DRAFT"
    return {"ok": True, "step": a.step}


def ask_user(s: Session, a: AskUserIn):
    """Ask the user one short question with a default. At most 3 per model."""
    if s.asks >= MAX_ASKS:
        return _err("the question limit is reached", f"use the default ({a.default}) and continue")
    s.asks += 1
    return {"ok": True, "asked": a.question, "default": a.default,
            "note": "if the user does not answer, continue with the default"}


# ================================================================ registry and visibility

TOOLS = {
    "list_capabilities": (NoInput, list_capabilities), "start_from_example": (StartFromExampleIn, start_from_example),
    "new_project": (NewProjectIn, new_project), "set_geometry": (SetGeometryIn, set_geometry),
    "set_physics": (SetPhysicsIn, set_physics), "set_materials": (SetMaterialsIn, set_materials),
    "set_conditions": (SetConditionsIn, set_conditions), "set_mesh": (SetMeshIn, set_mesh),
    "build_mesh": (NoInput, build_mesh), "show_mesh": (ShowMeshIn, show_mesh), "set_study": (SetStudyIn, set_study),
    "check_model": (NoInput, check_model_tool), "show_model": (NoInput, show_model), "run": (NoInput, run),
    "run_status": (NoInput, run_status), "show_results": (ShowResultsIn, show_results),
    "go_to_step": (GoToStepIn, go_to_step), "ask_user": (AskUserIn, ask_user), "compare": (CompareIn, compare),
    "answer_card": (AnswerCardIn, answer_card), "search_kb": (SearchKbIn, search_kb),
}
STEP_TOOLS = {"geometry": ["set_geometry"], "physics": ["set_physics"], "materials": ["set_materials"],
              "conditions": ["set_conditions"], "mesh": ["set_mesh", "build_mesh", "show_mesh"],
              "study": ["set_study"], "check": []}


def visible_tools(s: Session) -> list[str]:
    if s.state == "EMPTY":
        return ["list_capabilities", "start_from_example", "new_project", "search_kb", "ask_user"]
    if s.state == "DRAFT":
        step = STEP_TOOLS[s.focus]
        extra = ["check_model", "go_to_step"] + (["show_model", "search_kb"] if len(step) < 3 else []) + ["ask_user"]
        return step + extra
    if s.state == "CHECKED":
        return ["run", "show_model", "go_to_step", "ask_user"]
    if s.state == "RUNNING":
        return ["run_status"]
    if s.state == "COMPUTED":
        return ["show_results", "compare", "answer_card", "show_model", "go_to_step", "start_from_example"]
    return ["answer_card", "show_results", "compare", "go_to_step", "start_from_example"]


NEXT = {"geometry": "set_geometry", "physics": "set_physics", "materials": "set_materials",
        "conditions": "set_conditions", "mesh": "build_mesh", "study": "set_study", "check": "check_model"}


def next_step(s: Session) -> str:
    if s.state == "EMPTY":
        return "start_from_example (fast) or new_project"
    if s.state == "DRAFT":
        if s.focus == "mesh":
            if s.step_done("mesh"):
                return "check_model (or set_mesh and build_mesh again to change the mesh)"
            return "build_mesh (set_mesh first if the default size is not wanted)"
        return NEXT[s.focus] if s.focus != "check" else "check_model"
    return {"CHECKED": "run", "RUNNING": "run_status", "COMPUTED": "show_results, then answer_card",
            "REPORTED": "start_from_example or go_to_step"}[s.state]


def not_available(s: Session, name: str) -> str:
    return (f"'{name}' is not available in state {s.state}"
            + (f" (step {s.focus})" if s.state == "DRAFT" else "")
            + f". Next step: call {next_step(s)}. Available now: {', '.join(visible_tools(s))}.")


_EDITS = {"set_geometry", "set_physics", "set_materials", "set_conditions", "set_mesh", "set_study"}
_EDITABLE = ("name", "geometry", "physics", "materials", "boundary_conditions", "heat_sources", "initial",
             "mesh_settings", "study", "probes", "version", "state", "focus", "check", "mesh")


def output_time(times, want: float) -> float:
    """The output time equal to the requested one; a missing time is an error, never a silent substitute."""
    i = int(np.argmin(np.abs(np.asarray(times) - want)))
    if abs(times[i] - want) > 1e-6 * max(1.0, abs(want)):
        from .report import time_text
        raise ValueError(f"there is no output at {time_text(want)}; outputs exist at "
                         + ", ".join(time_text(float(x)) for x in times[-12:])
                         + ". Use one of these, or add the time to output_times with set_study and run again")
    return float(times[i])


def call(s: Session, name: str, args: dict | None = None) -> dict:
    """Validate, run and audit one tool call. Never raises for model mistakes."""
    if name not in TOOLS:
        out = _err(f"unknown tool '{name}'", f"available now: {', '.join(visible_tools(s))}")
    elif name not in visible_tools(s):
        out = _err(not_available(s, name))
    else:
        model_cls, fn = TOOLS[name]
        try:
            a = model_cls.model_validate(args or {})
        except ValidationError as e:
            out = _err("the tool input is not valid", "correct the listed fields", details=friendly_validation(e))
        else:
            saved = {k: getattr(s, k) if k in ("mesh", "check") else copy.deepcopy(getattr(s, k)) for k in _EDITABLE} \
                if name in _EDITS else None
            job = s.job
            try:
                out = fn(s, a)
            except (ValueError, KeyError, ArithmeticError, TranslationError, MeshError) as e:
                out = _err(str(e), "correct the input and call again")
            if saved is not None and not out.get("ok", False):
                for k, v in saved.items():  # a failed edit leaves the model as it was
                    setattr(s, k, v)
            elif saved is not None and job and job["id"] in JOBS._jobs \
                    and JOBS.status(job["id"]).status in ("queued", "running"):
                JOBS.cancel(job["id"])  # the run belongs to the model before this edit
                out.setdefault("note", "the run of the previous model was stopped")
                s.job = None
    out.setdefault("ok", False)
    out["state"] = s.state
    out["tree_summary"] = tree_summary(s.model, s.mesh["summary"] if s.mesh else None)
    out["next_step"] = next_step(s)
    out["available_tools"] = visible_tools(s)
    s.audit(name, args or {}, out["ok"], out.get("error", ""))
    _collect_numbers(s, out)
    return out


def _collect_numbers(s: Session, out: dict):
    """Numbers the program reported (the guardrail accepts them; the model did not make them up)."""
    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)) and math.isfinite(x):
            s.seen_numbers.add(float(x))
        elif isinstance(x, str):
            from .report import _NUM
            for m in _NUM.finditer(x):
                try:
                    s.seen_numbers.add(float(m.group(0).replace(",", "")))
                except ValueError:
                    pass
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x[:200]:
                walk(v)
    walk({k: v for k, v in out.items() if k not in ("available_tools",)})
