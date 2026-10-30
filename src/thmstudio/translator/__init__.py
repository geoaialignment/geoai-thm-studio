"""Translator: model tree + mesh bundle -> OpenGeoSys project file (.prj).

The LLM never writes OGS input. Each process has one serializer. Every unit
conversion the translator makes is written to the translation log so a report
can show it.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..mesh.contract import CORNERS, MeshBundle
from ..schema import Material, Model, boundary_normal, vertical_axis
from ..units import G

OGS_VERSION = "6.5.8"
OGS_TYPE = {"H": "LIQUID_FLOW", "T": "HEAT_CONDUCTION", "TH": "HT", "HC": "ComponentTransport",
            "HM": "HYDRO_MECHANICS", "TM": "THERMO_MECHANICS", "THM": "THERMO_HYDRO_MECHANICS"}
MECH = ("HM", "TM", "THM")
STEADY_DT = 1.0
DERIVED = {"heat_flux", "darcy_velocity", "sigma", "epsilon", "pressure_interpolated",
           "temperature_interpolated"}
MAX_STEPS = 5000
ITERATIVE_ABOVE = 6000  # coupled mechanics: elements above which the iterative preset is used
ITERATIVE_ABOVE_FLOW = 2000  # TH, HC and transient H (SparseLU is slow there and is refactorised every step)


class TranslationError(ValueError):
    pass


@dataclass
class BuildResult:
    prj: Path
    prefix: str
    output_times: list[float]
    t_end: float
    log: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)

    @property
    def primary(self) -> list[str]:
        """Solution fields every output file must contain (derived fields may be missing at t = 0)."""
        return [v for v in self.variables if v not in DERIVED]


# ---------------------------------------------------------------- xml helpers

def _sub(parent, tag, text=None, **attrib):
    e = ET.SubElement(parent, tag, {k: str(v) for k, v in attrib.items()})
    if text is not None:
        e.text = text if isinstance(text, str) else _num(text)
    return e


def _num(x: float) -> str:
    x = float(x)
    return str(int(x)) if x.is_integer() and abs(x) < 1e15 else repr(x)


def _prop(parent, name, value=None, ptype="Constant", **extra):
    p = _sub(parent, "property")
    _sub(p, "name", name)
    _sub(p, "type", ptype)
    if value is not None:
        _sub(p, "value", value)
    for k, v in extra.items():
        _sub(p, k, v)
    return p


# ---------------------------------------------------------------- measures with axisymmetric weight

def weighted_measure(mesh, axisymmetric: bool) -> float:
    """Length/area/volume of a mesh; for axisymmetric r-z meshes the revolved measure (2 pi r).

    Cell centres are exact centroids for straight segments, rectangles and triangles.
    """
    s = mesh.compute_cell_sizes(length=True, area=True, volume=True)
    for key in ("Volume", "Area", "Length"):
        v = np.abs(np.asarray(s.cell_data[key]))
        if v.sum() > 0:
            break
    if not axisymmetric:
        return float(v.sum())
    r = mesh.cell_centers().points[:, 0]
    return float(np.sum(2 * math.pi * r * v))


# ---------------------------------------------------------------- time grid

def time_steps(model: Model) -> tuple[list[float], list[float]]:
    """Time step sizes and the output times on the step grid (OGS accumulates t += dt)."""
    st = model.study
    if st.kind == "steady":
        return [STEADY_DT], [STEADY_DT]
    T = st.end_time
    dt0 = st.first_step or T / 100.0
    dtmax = st.max_step or (T / 20.0 if st.growth > 1.0 else dt0)
    breaks = sorted(set([t for t in st.output_times] + [T]))
    dts, t, k, step = [], 0.0, 0, min(dt0, dtmax)
    while t < T * (1 - 1e-12):
        dt = step
        step = min(step * st.growth, dtmax)  # grow from the capped step, so the power never overflows
        nxt = breaks[k]
        if t + dt >= nxt * (1 - 1e-9):
            dt = nxt - t
            k += 1
        dts.append(dt)
        t += dt
        if len(dts) > MAX_STEPS:
            raise TranslationError(f"more than {MAX_STEPS} time steps; use a larger first_step, growth or max_step")
    times, t = [], 0.0
    for dt in dts:
        t += dt
        times.append(t)
    outs = [times[min(range(len(times)), key=lambda j: abs(times[j] - b))] for b in breaks]
    return dts, outs


def _pairs(dts):
    out = []
    for dt in dts:
        if out and abs(out[-1][1] - dt) <= 1e-12 * dt:
            out[-1][0] += 1
        else:
            out.append([1, dt])
    return out


# ---------------------------------------------------------------- material helpers

def permeability(m: Material, model: Model, log: list[str], region: str) -> float:
    f = model.physics.fluid
    if m.permeability is not None:
        return m.permeability
    if m.hydraulic_conductivity is not None:
        k = m.hydraulic_conductivity * f.viscosity / (f.density * G)
        log.append(f"{region}: hydraulic conductivity {m.hydraulic_conductivity:.4g} m/s -> permeability "
                   f"{k:.4g} m2 (viscosity {f.viscosity:.4g} Pa s, density {f.density:.4g} kg/m3, g {G})")
        return k
    raise TranslationError(f"region '{region}' needs permeability or hydraulic_conductivity")


def storage(m: Material, model: Model, log: list[str], region: str) -> float:
    if model.study.kind == "steady":
        return 0.0
    if m.specific_storage is None:
        return 0.0
    f = model.physics.fluid
    s = m.specific_storage / (f.density * G)
    log.append(f"{region}: specific storage {m.specific_storage:.4g} 1/m -> storage {s:.4g} 1/Pa")
    return s


def bulk_heat_capacity(m: Material, model: Model, log: list[str], region: str) -> tuple[float, float]:
    """(density, specific heat) of the saturated bulk for heat conduction alone."""
    if m.density is not None and m.specific_heat is not None:
        return m.density, m.specific_heat
    f = model.physics.fluid
    if None not in (m.porosity, m.solid_density, m.solid_specific_heat):
        phi = m.porosity
        rho = phi * f.density + (1 - phi) * m.solid_density
        rc = phi * f.density * f.specific_heat + (1 - phi) * m.solid_density * m.solid_specific_heat
        log.append(f"{region}: bulk density {rho:.5g} kg/m3 and heat capacity {rc / rho:.5g} J/kg/K from porosity "
                   f"{phi:.3g}, solid and water values")
        return rho, rc / rho
    raise TranslationError(f"region '{region}' needs density and specific_heat (bulk), or porosity, "
                           f"solid_density and solid_specific_heat")


# ---------------------------------------------------------------- project builder

_COMP = {"x": 0, "r": 0, "y": 1, "z": 1}


def _displacement_bc(bcs, bc, model, mesh, pname, add_param, dim, log):
    """roller: normal component 0; fixed: one or all components; load: normal traction, compression positive."""
    ax, sign = boundary_normal(model.geometry, bc.boundary)
    if bc.kind == "roller":
        comps, val, typ = [ax], 0.0, "Dirichlet"
    elif bc.kind == "fixed":
        if bc.component is None:
            comps = list(range(dim))
        else:
            c = {"x": 0, "r": 0, "y": 1, "z": 1 if dim == 2 else 2}[bc.component]
            comps = [c]
        val, typ = bc.value, "Dirichlet"
    else:  # load: traction t = -sigma_n n, with the outward normal along axis 'ax'
        comps, val, typ = [ax], -bc.value * sign, "Neumann"
        log.append(f"boundary {bc.boundary}: normal load {bc.value:.4g} Pa (compression) -> traction "
                   f"{val:.4g} Pa on component {ax}")
    add_param(pname, val)
    for c in comps:
        e = _sub(bcs, "boundary_condition")
        _sub(e, "mesh", mesh)
        _sub(e, "type", typ)
        _sub(e, "component", c)
        _sub(e, "parameter", pname)


def _mech_medium(med, m: Material, model: Model, region: str, log: list[str]):
    """Media for HM, TM and THM (linear elastic solid; constants only)."""
    proc, f = model.physics.process, model.physics.fluid
    phases = _sub(med, "phases")
    if proc in ("HM", "THM"):
        ph = _sub(phases, "phase")
        _sub(ph, "type", "AqueousLiquid")
        fp = _sub(ph, "properties")
        _prop(fp, "viscosity", f.viscosity)
        if proc == "THM":
            _prop(fp, "specific_heat_capacity", f.specific_heat)
            _prop(fp, "thermal_conductivity", f.thermal_conductivity)
            # Constant density with a thermal expansivity: this is the linear theory the point-source
            # solution assumes. A temperature-dependent density counted the expansion a second time
            # and went negative near a point source on fine meshes (tested on V5).
            _prop(fp, "density", f.density)
            _prop(fp, "thermal_expansivity", f.thermal_expansion)
        else:
            _prop(fp, "density", f.density)
    sol = _sub(phases, "phase")
    _sub(sol, "type", "Solid")
    sp = _sub(sol, "properties")
    if proc == "TM":
        rho, c = bulk_heat_capacity(m, model, log, region)
        if model.study.kind == "steady":
            c = 0.0
        _prop(sp, "density", rho)
        _prop(sp, "thermal_conductivity", m.thermal_conductivity)
        _prop(sp, "specific_heat_capacity", c)
        _prop(sp, "thermal_expansivity", m.thermal_expansion or 0.0)
        _sub(med, "properties")
        return
    _prop(sp, "density", m.solid_density or 2000.0)
    if m.solid_density is None:
        log.append(f"{region}: solid density not given; 2000 kg/m3 written (no effect without gravity"
                   + (" and heat" if proc == "HM" else "") + ")")
    if proc == "THM":
        phi = m.porosity
        lam_s = (m.thermal_conductivity - phi * f.thermal_conductivity) / (1 - phi) if phi < 1 else 0.0
        _prop(sp, "thermal_conductivity", max(lam_s, 0.0))
        _prop(sp, "specific_heat_capacity", m.solid_specific_heat)
        _prop(sp, "thermal_expansivity", m.thermal_expansion or 0.0)
    props = _sub(med, "properties")
    _prop(props, "permeability", permeability(m, model, log, region))
    _prop(props, "porosity", m.porosity)
    _prop(props, "biot_coefficient", m.biot_coefficient if m.biot_coefficient is not None else 1.0)
    if m.biot_coefficient is None:
        log.append(f"{region}: Biot coefficient not given; 1 is used (incompressible grains)")
    if proc == "HM":
        _prop(props, "reference_temperature", 293.15)
    else:
        _prop(props, "thermal_conductivity", m.thermal_conductivity)


def _head_to_pressure(model: Model, head_expr: str) -> str:
    """OGS expression for p = rho g (h - elevation) (elevation 0 without gravity)."""
    rho = model.physics.fluid.density
    ax = vertical_axis(model.geometry) if model.gravity_on else None
    elev = ax if ax else "0"
    return f"{_num(rho * G)}*(({head_expr}) - {elev})"


def translate(model: Model, bundle: MeshBundle, builddir: Path, integration_order: int | None = None,
              solver: str = "auto") -> BuildResult:
    """solver: 'auto' (presets below), 'direct' or 'iterative' (verification of the presets)."""
    proc = model.physics.process
    mech = proc in MECH
    log: list[str] = []
    root = ET.Element("OpenGeoSysProject")
    axis = bundle.axisymmetric
    files = bundle.files
    if not files:
        raise TranslationError("the mesh has not been written")

    # meshes: bulk, boundaries used by conditions, regions used by sources
    used_b = sorted({bc.boundary for bc in model.boundary_conditions if bc.boundary not in bundle.point_meshes})
    used_pb = sorted({bc.boundary for bc in model.boundary_conditions if bc.boundary in bundle.point_meshes})
    auto_axis = mech and model.geometry.kind == "axisym_source" and not any(
        bc.boundary == "axis" and bc.variable == "displacement" for bc in model.boundary_conditions)
    if auto_axis:
        used_b = sorted(set(used_b) | {"axis"})
    used_r = sorted({hs.region for hs in model.heat_sources if hs.region not in bundle.point_meshes})
    used_p = sorted({hs.region for hs in model.heat_sources if hs.region in bundle.point_meshes} | set(used_pb))
    for b in used_b:
        if b not in bundle.boundaries:
            raise TranslationError(f"boundary '{b}' is not in the mesh (available: {', '.join(sorted(bundle.boundaries))})")
    for r in used_r:
        if r not in bundle.region_meshes:
            raise TranslationError(f"region '{r}' is not in the mesh")
    meshes = _sub(root, "meshes")
    mesh_name = {}
    for key in (["bulk"] + [f"boundary:{b}" for b in used_b] + [f"region:{r}" for r in used_r]
                + [f"point:{q}" for q in used_p]):
        fn = files[key]
        attrs = {"axially_symmetric": "true"} if axis else {}
        _sub(meshes, "mesh", fn, **attrs)
        mesh_name[key] = fn[:-4]

    # process
    procs = _sub(root, "processes")
    p = _sub(procs, "process")
    _sub(p, "name", "main")
    _sub(p, "type", OGS_TYPE[proc])
    _sub(p, "integration_order", integration_order or (3 if bundle.order == 2 else 2))
    if mech:
        cr = _sub(p, "constitutive_relation")
        _sub(cr, "type", "LinearElasticIsotropic")
        _sub(cr, "youngs_modulus", "E")
        _sub(cr, "poissons_ratio", "nu")
    pv_el = _sub(p, "process_variables")
    dim = bundle.dim
    if model.gravity_on:
        ax = vertical_axis(model.geometry)
        gvec = [0.0] * dim
        gvec[{"y": 1, "z": 2}[ax]] = -G
    else:
        gvec = [0.0] * dim
    comp = model.physics.components[0] if model.physics.components else None
    if proc == "T":
        _sub(pv_el, "process_variable", "temperature")
        sec = _sub(p, "secondary_variables")
        _sub(sec, "secondary_variable", internal_name="heat_flux", output_name="heat_flux")
        variables = ["temperature", "heat_flux"]
    elif proc == "H":
        _sub(pv_el, "process_variable", "pressure")
        sec = _sub(p, "secondary_variables")
        _sub(sec, "secondary_variable", internal_name="darcy_velocity", output_name="darcy_velocity")
        _sub(p, "specific_body_force", " ".join(_num(v) for v in gvec))
        _sub(p, "equation_balance_type", "volume")
        log.append("liquid flow is solved as a volume balance; flux conditions are volumetric (m3/m2/s)")
        variables = ["pressure", "darcy_velocity"]
    elif proc == "TH":
        _sub(pv_el, "temperature", "temperature")
        _sub(pv_el, "pressure", "pressure")
        _sub(p, "specific_body_force", " ".join(_num(v) for v in gvec))
        sec = _sub(p, "secondary_variables")
        _sub(sec, "secondary_variable", internal_name="darcy_velocity", output_name="darcy_velocity")
        variables = ["temperature", "pressure", "darcy_velocity"]
    elif proc == "HC":
        if comp is None:
            raise TranslationError("transport needs a component")
        _sub(pv_el, "concentration", comp.name)
        _sub(pv_el, "pressure", "pressure")
        _sub(p, "specific_body_force", " ".join(_num(v) for v in gvec))
        sec = _sub(p, "secondary_variables")
        _sub(sec, "secondary_variable", internal_name="darcy_velocity", output_name="darcy_velocity")
        variables = [comp.name, "pressure", "darcy_velocity"]
    elif mech:
        if proc in ("TM", "THM"):
            _sub(pv_el, "temperature", "temperature")
        if proc in ("HM", "THM"):
            _sub(pv_el, "pressure", "pressure")
        _sub(pv_el, "displacement", "displacement")
        sec = _sub(p, "secondary_variables")
        _sub(sec, "secondary_variable", name="sigma")
        _sub(sec, "secondary_variable", name="epsilon")
        if proc == "HM":
            _sub(sec, "secondary_variable", internal_name="velocity", output_name="darcy_velocity")
        _sub(p, "specific_body_force", " ".join(_num(v) for v in gvec))
        if proc == "THM":
            _sub(p, "equation_balance_type", "mass")
            log.append("THM is solved as a mass balance; water flux conditions are converted to mass flux")
        variables = (["temperature"] if proc in ("TM", "THM") else []) + (["pressure"] if proc != "TM" else []) \
            + ["displacement", "sigma", "epsilon"] + (["darcy_velocity"] if proc == "HM" else [])
        if bundle.order == 2:
            variables += [f"{v}_interpolated" for v in ("temperature", "pressure") if v in variables]
    else:
        raise TranslationError(f"process {proc} is not available in this version")
    # Linear processes: one solve per step, and (heat conduction) reuse of the factorisation while
    # the step size is unchanged. Never for TH or HC: there the flow velocity couples the equations
    # (tested: the reuse gives a wrong solute front).
    if proc in ("T", "H"):
        _sub(p, "linear", "true")
    if proc == "T":
        _sub(p, "linear_solver_compute_only_upon_timestep_change", "true")

    # media: one medium per region (MaterialID)
    media = _sub(root, "media")
    f = model.physics.fluid
    for region, mid in sorted(bundle.regions.items(), key=lambda kv: kv[1]):
        m = model.materials.get(region)
        if m is None:
            raise TranslationError(f"region '{region}' has no material")
        med = _sub(media, "medium", id=mid)
        if proc == "T":
            _sub(med, "phases")
            props = _sub(med, "properties")
            if m.thermal_conductivity is None:
                raise TranslationError(f"region '{region}' needs thermal_conductivity")
            if model.study.kind == "steady":  # no storage term: density and heat capacity do not enter
                rho, c = m.density or 1.0, 0.0
            else:
                rho, c = bulk_heat_capacity(m, model, log, region)
            _prop(props, "thermal_conductivity", m.thermal_conductivity)
            _prop(props, "density", rho)
            _prop(props, "specific_heat_capacity", c)
            continue
        if mech:
            _mech_medium(med, m, model, region, log)
            continue
        phases = _sub(med, "phases")
        ph = _sub(phases, "phase")
        _sub(ph, "type", "AqueousLiquid")
        if proc == "HC":
            comps = _sub(ph, "components")
            c_el = _sub(comps, "component")
            _sub(c_el, "name", comp.name)
            cprops = _sub(c_el, "properties")
            R = comp.retardation.get(region, 1.0) if isinstance(comp.retardation, dict) else comp.retardation
            _prop(cprops, "pore_diffusion", comp.pore_diffusion)
            _prop(cprops, "retardation_factor", R)
            _prop(cprops, "decay_rate", comp.decay)
        fprops = _sub(ph, "properties")
        if proc == "HC" and f.density_increase_per_concentration > 0:
            # buoyancy: rho = rho0 (1 + slope c), slope relative to rho0
            dens = _prop(fprops, "density", None, ptype="Linear", reference_value=_num(f.density))
            iv = _sub(dens, "independent_variable")
            _sub(iv, "variable_name", "concentration")
            _sub(iv, "reference_condition", 0)
            _sub(iv, "slope", f.density_increase_per_concentration / f.density)
            if not any("density" in l and "concentration" in l for l in log):
                log.append(f"water density {f.density:.4g} kg/m3 + {f.density_increase_per_concentration:.4g} kg/m3 "
                           "per unit concentration (buoyancy-driven flow)")
        else:
            _prop(fprops, "density", f.density)
        _prop(fprops, "viscosity", f.viscosity)
        if proc == "TH":
            _prop(fprops, "specific_heat_capacity", f.specific_heat)
            _prop(fprops, "thermal_conductivity", f.thermal_conductivity)
            sol = _sub(phases, "phase")
            _sub(sol, "type", "Solid")
            sprops = _sub(sol, "properties")
            for need in ("porosity", "solid_density", "solid_specific_heat", "thermal_conductivity"):
                if getattr(m, need) is None:
                    raise TranslationError(f"region '{region}' needs {need} for heat transport with flow")
            _prop(sprops, "storage", storage(m, model, log, region))
            _prop(sprops, "density", m.solid_density)
            _prop(sprops, "specific_heat_capacity", m.solid_specific_heat)
            # HT requires a solid conductivity; the medium value below is the effective one.
            # The solid value is chosen so that porosity mixing gives the same effective value.
            phi = m.porosity
            lam_s = (m.thermal_conductivity - phi * f.thermal_conductivity) / (1 - phi) if phi < 1 else 0.0
            _prop(sprops, "thermal_conductivity", max(lam_s, 0.0))
        props = _sub(med, "properties")
        _prop(props, "permeability", permeability(m, model, log, region))
        if proc == "H":
            _prop(props, "porosity", m.porosity if m.porosity is not None else 1.0)
            _prop(props, "storage", storage(m, model, log, region))
            _prop(props, "reference_temperature", 293.15)
        elif proc == "TH":
            _prop(props, "porosity", m.porosity)
            _prop(props, "thermal_conductivity", m.thermal_conductivity)
            _prop(props, "thermal_longitudinal_dispersivity", 0.0)
            _prop(props, "thermal_transversal_dispersivity", 0.0)
        elif proc == "HC":
            if m.porosity is None:
                raise TranslationError(f"region '{region}' needs porosity for transport")
            _prop(props, "porosity", m.porosity)
            _prop(props, "longitudinal_dispersivity", m.longitudinal_dispersivity or 0.0)
            _prop(props, "transversal_dispersivity", m.transverse_dispersivity or 0.0)
            s = storage(m, model, log, region)
            if s:
                _prop(props, "storage", s)

    # time loop
    dts, outs = time_steps(model)
    t_end = sum(dts)  # same left-to-right accumulation as OGS
    tl = _sub(root, "time_loop")
    tps = _sub(tl, "processes")
    tp = _sub(tps, "process", ref="main")
    _sub(tp, "nonlinear_solver", "newton" if mech else "picard")
    cc = _sub(tp, "convergence_criterion")
    if mech:
        # component order in OGS (read from the logs): HM p,u; TM T,u; THM T,p,u. Absolute tolerances sit above
        # round-off of each variable, so a field that decays to zero (pore pressure after consolidation) converges.
        tol = ({"TM": ["1e-8"], "HM": ["1e-3"], "THM": ["1e-8", "1e-3"]}[proc]) + ["1e-12"] * dim
        _sub(cc, "type", "PerComponentDeltaX")
        _sub(cc, "norm_type", "NORM2")
        _sub(cc, "abstols", " ".join(tol))
        _sub(cc, "reltols", " ".join(["1e-10"] * len(tol)))
    elif proc in ("T", "H"):
        _sub(cc, "type", "DeltaX")
        _sub(cc, "norm_type", "NORM2")
        _sub(cc, "abstol", 1e-9 if proc == "T" else 1e-6)
    else:
        abst = {"TH": "1e-9 1e-6", "HC": "1e-6 1e-12"}[proc]  # OGS order (from the logs): TH T,p; HC p,c
        _sub(cc, "type", "PerComponentDeltaX")
        _sub(cc, "norm_type", "NORM2")
        _sub(cc, "abstols", abst)
        buoyant = proc == "HC" and model.physics.fluid.density_increase_per_concentration > 0
        # either is enough; relative covers iterative-solver noise. With density coupling Picard converges slowly
        # and oscillates; the official Elder benchmark accepts a relative change of 1e-3 per component (E2 checks
        # the result against that benchmark).
        _sub(cc, "reltols", "1e-3 1e-3" if buoyant else "1e-10 1e-10")
    td = _sub(tp, "time_discretization")
    _sub(td, "type", "BackwardEuler")
    ts = _sub(tp, "time_stepping")
    _sub(ts, "type", "FixedTimeStepping")
    _sub(ts, "t_initial", 0.0)
    _sub(ts, "t_end", t_end)
    tsp = _sub(ts, "timesteps")
    for rep, dt in _pairs(dts):
        pair = _sub(tsp, "pair")
        _sub(pair, "repeat", rep)
        _sub(pair, "delta_t", dt)
    out = _sub(tl, "output")
    _sub(out, "type", "VTK")
    prefix = model.name
    _sub(out, "prefix", prefix)
    _sub(out, "suffix", "_ts_{:timestep}_t_{:time}")
    ots = _sub(out, "timesteps")
    pair = _sub(ots, "pair")
    _sub(pair, "repeat", 1)
    _sub(pair, "each_steps", len(dts))
    ov = _sub(out, "variables")
    for v in variables + ["MaterialIDs"]:
        _sub(ov, "variable", v)
    if model.study.kind == "transient" and outs:
        _sub(out, "fixed_output_times", " ".join(_num(t) for t in outs))

    # parameters and process variables
    params_el = _sub(root, "parameters")
    pvs = _sub(root, "process_variables")
    ini = model.initial

    def add_param(name, value=None, expression=None):
        pe = _sub(params_el, "parameter")
        _sub(pe, "name", name)
        if expression is None:
            _sub(pe, "type", "Constant")
            _sub(pe, "value", value)
        else:
            _sub(pe, "type", "Function")
            _sub(pe, "expression", expression)
        return name

    def new_pv(name, initial_param):
        e = _sub(pvs, "process_variable")
        _sub(e, "name", name)
        _sub(e, "components", 1)
        _sub(e, "order", 1)
        _sub(e, "initial_condition", initial_param)
        return e, _sub(e, "boundary_conditions")

    pv_bcs = {}
    if mech:
        e = _sub(pvs, "process_variable")
        _sub(e, "name", "displacement")
        _sub(e, "components", dim)
        _sub(e, "order", 2)
        pe = _sub(params_el, "parameter")
        _sub(pe, "name", "u_initial")
        _sub(pe, "type", "Constant")
        _sub(pe, "values", " ".join(["0"] * dim))
        _sub(e, "initial_condition", "u_initial")
        pv_bcs["displacement"] = (e, _sub(e, "boundary_conditions"))
        for name, values in (("E", {r: model.materials[r].youngs_modulus for r in bundle.regions}),
                             ("nu", {r: model.materials[r].poissons_ratio for r in bundle.regions})):
            if any(v is None for v in values.values()):
                missing = [r for r, v in values.items() if v is None]
                raise TranslationError(f"regions {missing} need {'youngs_modulus' if name == 'E' else 'poissons_ratio'}")
            pe = _sub(params_el, "parameter")
            _sub(pe, "name", name)
            _sub(pe, "type", "Group")
            _sub(pe, "group_id_property", "MaterialIDs")
            for r, mid in sorted(bundle.regions.items(), key=lambda kv: kv[1]):
                iv = _sub(pe, "index_values")
                _sub(iv, "index", mid)
                _sub(iv, "value", values[r])
        if auto_axis:
            e = _sub(pv_bcs["displacement"][1], "boundary_condition")
            _sub(e, "mesh", mesh_name["boundary:axis"])
            _sub(e, "type", "Dirichlet")
            _sub(e, "component", 0)
            add_param("u_axis", 0.0)
            _sub(e, "parameter", "u_axis")
            log.append("axis r = 0: radial displacement fixed to 0 (symmetry)")
    if proc in ("T", "TH", "TM", "THM"):
        if ini.temperature is None:
            raise TranslationError("initial temperature is missing")
        pv_bcs["temperature"] = new_pv("temperature", add_param("T_initial", ini.temperature))
    if proc in ("H", "TH", "HC", "HM", "THM"):
        if ini.head is not None:
            init = add_param("p_initial", expression=_head_to_pressure(model, _num(ini.head)))
            log.append(f"initial head {ini.head:.4g} m -> hydrostatic pressure p = rho g (h - elevation)"
                       if model.gravity_on else f"initial head {ini.head:.4g} m -> pressure rho g h")
        elif ini.pressure is not None:
            init = add_param("p_initial", ini.pressure)
        else:
            raise TranslationError("initial head or pressure is missing")
        pv_bcs["pressure"] = new_pv("pressure", init)
    if proc == "HC":
        pv_bcs["concentration"] = new_pv(comp.name, add_param("c_initial", ini.concentration or 0.0))

    for i, bc in enumerate(model.boundary_conditions):
        var = "pressure" if bc.variable in ("head", "pressure") else bc.variable
        if var not in pv_bcs:
            raise TranslationError(f"variable '{bc.variable}' is not part of process {proc}")
        _, bcs = pv_bcs[var]
        pname = f"bc{i}_{bc.boundary}"
        if var == "displacement":
            _displacement_bc(bcs, bc, model, mesh_name[f"boundary:{bc.boundary}"], pname, add_param, dim, log)
            continue
        e = _sub(bcs, "boundary_condition")
        is_point = bc.boundary in bundle.point_meshes
        _sub(e, "mesh", mesh_name[f"point:{bc.boundary}" if is_point else f"boundary:{bc.boundary}"])
        if is_point and bc.kind != "fixed":
            raise TranslationError(f"'{bc.boundary}' is a point: only fixed values can be set there")
        if bc.kind == "fixed":
            _sub(e, "type", "Dirichlet")
            if bc.expression is not None:
                expr = _head_to_pressure(model, bc.expression) if bc.variable == "head" else bc.expression
                add_param(pname, expression=expr)
            elif bc.variable == "head":
                add_param(pname, expression=_head_to_pressure(model, _num(bc.value)))
                log.append(f"boundary {bc.boundary}: head {bc.value:.4g} m -> pressure "
                           + ("rho g (h - elevation)" if model.gravity_on else "rho g h"))
            else:
                add_param(pname, bc.value)
        else:
            _sub(e, "type", "Neumann")
            area = weighted_measure(bundle.boundaries[bc.boundary], axis)
            val = bc.value
            if bc.kind == "rate":
                val = bc.value / area
                unit = "m3/s" if var == "pressure" else "W"
                log.append(f"boundary {bc.boundary}: total {bc.value:.4g} {unit} spread over "
                           f"{area:.4g} {'m2' if dim == 3 or axis else 'm2 (per m thickness)'} -> {val:.4g} per m2")
            if var == "pressure" and proc in ("HC", "THM"):
                val *= f.density
                log.append(f"boundary {bc.boundary}: water flux x density {f.density:.4g} -> mass flux "
                           f"{val:.4g} kg/m2/s (transport solves a mass balance)")
            add_param(pname, val)
        _sub(e, "parameter", pname)

    for i, hs in enumerate(model.heat_sources):
        if "temperature" not in pv_bcs:
            raise TranslationError("heat sources need a thermal process")
        pv_e, _ = pv_bcs["temperature"]
        sts = pv_e.find("source_terms")
        if sts is None:
            sts = _sub(pv_e, "source_terms")
        e = _sub(sts, "source_term")
        half = model.geometry.kind == "axisym_source" and model.geometry.symmetric
        if hs.region in bundle.point_meshes:
            if hs.kind != "power":
                raise TranslationError("a point source needs kind 'power' (W)")
            _sub(e, "mesh", mesh_name[f"point:{hs.region}"])
            _sub(e, "type", "Nodal")
            val = hs.value * (0.5 if half else 1.0)
            log.append(f"point source: {hs.value:.4g} W" + (" -> 0.5 x in the modelled half (symmetry plane)"
                                                           if half else ""))
        else:
            _sub(e, "mesh", mesh_name[f"region:{hs.region}"])
            _sub(e, "type", "Volumetric")
            val = hs.value
            if hs.kind == "power":
                vol = weighted_measure(bundle.region_meshes[hs.region], axis) * (2.0 if half else 1.0)
                val = hs.value / vol
                log.append(f"heat source {hs.region}: {hs.value:.4g} W over {vol:.4g} "
                           f"{'m3' if dim == 3 or axis else 'm2 x 1 m'}" + (" (both halves)" if half else "")
                           + f" -> {val:.4g} W/m3")
        pname = add_param(f"q{i}_{hs.region}", val)
        _sub(e, "parameter", pname)

    # solvers
    nls = _sub(root, "nonlinear_solvers")
    ns = _sub(nls, "nonlinear_solver")
    _sub(ns, "name", "newton" if mech else "picard")
    _sub(ns, "type", "Newton" if mech else "Picard")
    _sub(ns, "max_iter", 60 if proc == "HC" and model.physics.fluid.density_increase_per_concentration > 0 else 20)
    _sub(ns, "linear_solver", "direct")
    lss = _sub(root, "linear_solvers")
    ls = _sub(lss, "linear_solver")
    _sub(ls, "name", "direct")
    eig = _sub(ls, "eigen")
    iterative = solver == "iterative" or (solver == "auto" and (
        (mech and bundle.bulk.n_cells > ITERATIVE_ABOVE) or
        (proc in ("TH", "HC") and bundle.bulk.n_cells > ITERATIVE_ABOVE_FLOW) or
        (proc == "H" and model.study.kind == "transient" and bundle.bulk.n_cells > ITERATIVE_ABOVE_FLOW)))
    if iterative:
        # verified presets (agreement with SparseLU on E1, V1b, V3, V6): faster on larger meshes
        _sub(eig, "solver_type", "BiCGSTAB")
        _sub(eig, "precon_type", "ILUT")
        _sub(eig, "max_iteration_step", 10000)
        _sub(eig, "error_tolerance", 1e-12)
        log.append(f"linear solver: BiCGSTAB with ILUT ({bundle.bulk.n_cells} elements)")
    else:
        _sub(eig, "solver_type", "SparseLU")
    _sub(eig, "scaling", "true")

    ET.indent(root, space="    ")
    builddir.mkdir(parents=True, exist_ok=True)
    path = builddir / f"{model.name}.prj"
    ET.ElementTree(root).write(path, encoding="ISO-8859-1", xml_declaration=True)
    return BuildResult(prj=path, prefix=prefix, output_times=outs, t_end=t_end, log=log, variables=variables)
