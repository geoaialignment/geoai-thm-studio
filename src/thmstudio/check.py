"""check_model: is this model tree complete, consistent, supported and resolved well enough to run?

Errors block the run; warnings do not. Every issue says how to fix it.
"""
from __future__ import annotations

import difflib
import math

import numpy as np

from . import configs
from .mesh.quality import Issue
from .schema import (MECHANICS, VARIABLES, Model, boundaries_of, boundary_normal, interfaces_of, is_axisymmetric,
                     points_of, regions_of, vertical_axis)
from .translator import MAX_STEPS, TranslationError, time_steps
from .units import G, YEAR

NEEDS = {  # process -> material properties needed (alternatives separated by |)
    "H": ["permeability|hydraulic_conductivity"],
    "T": ["thermal_conductivity"],
    "TH": ["permeability|hydraulic_conductivity", "porosity", "thermal_conductivity", "solid_density",
           "solid_specific_heat"],
    "HC": ["permeability|hydraulic_conductivity", "porosity"],
    "HM": ["permeability|hydraulic_conductivity", "porosity", "youngs_modulus", "poissons_ratio"],
    "TM": ["thermal_conductivity", "youngs_modulus", "poissons_ratio"],
    "THM": ["permeability|hydraulic_conductivity", "porosity", "thermal_conductivity", "solid_density",
            "solid_specific_heat", "youngs_modulus", "poissons_ratio"],
}
PLAUSIBLE = {  # property -> (low, high, unit) outside which a warning is given
    "hydraulic_conductivity": (1e-14, 1e-2, "m/s"), "permeability": (1e-21, 1e-9, "m2"),
    "porosity": (0.001, 0.6, "-"), "specific_storage": (1e-8, 1e-2, "1/m"),
    "thermal_conductivity": (0.1, 60.0, "W/m/K"), "solid_density": (1000, 8000, "kg/m3"),
    "density": (1000, 8000, "kg/m3"), "solid_specific_heat": (100, 3000, "J/kg/K"),
    "specific_heat": (100, 5000, "J/kg/K"), "longitudinal_dispersivity": (0, 100, "m"),
    "youngs_modulus": (1e6, 3e11, "Pa"), "poissons_ratio": (0.05, 0.45, "-"), "thermal_expansion": (1e-7, 1e-4, "1/K"),
}


def _closest(name, options):
    m = difflib.get_close_matches(name, options, n=1, cutoff=0.5)
    return f" Did you mean '{m[0]}'?" if m else ""


def _fmt(x):
    return f"{x:.3g}"


def extents(model: Model) -> dict[str, float]:
    g = model.geometry
    if g.kind == "rect":
        return {"x": g.width, "y": sum(l.thickness for l in g.layers)}
    if g.kind == "strip":
        return {"x": sum(s.thickness for s in g.segments), "y": g.width}
    if g.kind == "rect_inclusion":
        return {"x": g.width, "y": g.height}
    if g.kind == "axisym_well":
        return {"r": g.outer_radius - g.well_radius, "z": sum(l.thickness for l in g.layers)}
    if g.kind == "axisym_source":
        return {"r": g.outer_radius, "z": g.height}
    return {"x": g.length_x, "y": g.length_y, "z": sum(l.thickness for l in g.layers)}


def check_model(model: Model, mesh_info: dict | None = None) -> dict:
    """mesh_info: {'hash': model hash the mesh was built for, 'report': quality report dict,
    'boundary_sizes': {boundary: size of adjacent elements}, 'size_max': float}"""
    issues: list[Issue] = []
    err = lambda code, msg, fix="": issues.append(Issue("error", code, msg, fix))
    warn = lambda code, msg, fix="": issues.append(Issue("warning", code, msg, fix))
    g, ph = model.geometry, model.physics
    proc = ph.process

    # configuration
    cfg = configs.find(proc, g.kind, getattr(g, "source", None),
                       buoyant=ph.fluid.density_increase_per_concentration > 0)
    if cfg is None:
        shapes = configs.supported_shapes(proc)
        err("unsupported_configuration",
            f"process {proc} on shape '{g.kind}' is not a verified configuration (verified shapes for {proc}: "
            f"{', '.join(shapes) or 'none'}). {configs.CONTACT}",
            f"choose one of: {', '.join(shapes)}" if shapes else "")
    else:
        from .report import verification_status
        bad = [c for c in verification_status(model)["cases"] if c["status"] != "passed"]
        if bad:
            err("verification_missing", f"{cfg.id} is computed only when all its verification cases have passed with "
                f"this version; " + ", ".join(f"{c['case']} {c['status']}" for c in bad),
                "run: thmstudio verify " + " ".join(c["case"] for c in bad))
    if cfg is not None and model.study.kind == "steady" and not cfg.steady:
        err("steady_not_supported", f"{cfg.id} is verified for transient studies only",
            "use set_study with kind 'transient' and an end_time")

    # names
    regions = regions_of(g)
    for kind, names in (("region", regions), ("boundary", boundaries_of(g))):
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            err("duplicate_name", f"the {kind} name{'s' if len(dup) > 1 else ''} {', '.join(dup)} occur more than once",
                "give every layer, segment and boundary part its own name with set_geometry")
    clash = sorted(set(regions) & {"left", "right", "bottom", "top", "front", "back", "well", "outer", "axis"})
    if clash:
        err("duplicate_name", f"region name {', '.join(clash)} is also a boundary name", "rename the region")
    for comp in ph.components:
        if isinstance(comp.retardation, dict):
            for r in comp.retardation:
                if r not in regions:
                    err("unknown_region", f"retardation is given for '{r}', which is not a region "
                        f"(regions: {', '.join(regions)}).{_closest(r, regions)}", "rename or remove it")

    # materials
    for r in regions:
        if r not in model.materials:
            err("missing_material", f"region '{r}' has no material", f"use set_materials for region '{r}'")
    for name in model.materials:
        if name not in regions:
            err("unknown_region", f"materials are given for '{name}', which is not a region "
                f"(regions: {', '.join(regions)}).{_closest(name, regions)}", "rename or remove it")
    for r, m in model.materials.items():
        if r not in regions:
            continue
        for need in NEEDS[proc]:
            alts = need.split("|")
            if all(getattr(m, a) is None for a in alts):
                err("missing_property", f"region '{r}' needs {' or '.join(alts)} for process {proc}",
                    f"use set_materials for region '{r}'")
        if proc == "T" and model.study.kind == "transient":
            if not ((m.density and m.specific_heat) or (m.porosity and m.solid_density and m.solid_specific_heat)):
                err("missing_property", f"region '{r}' needs density and specific_heat (or porosity, solid_density "
                    "and solid_specific_heat) for a transient heat study", f"use set_materials for region '{r}'")
        if proc in ("TH", "THM") and m.thermal_conductivity is not None and m.porosity is not None and \
                m.thermal_conductivity < m.porosity * ph.fluid.thermal_conductivity:
            err("conductivity_too_low", f"region '{r}': effective thermal conductivity {_fmt(m.thermal_conductivity)} W/m/K "
                f"is below the share of the water alone ({_fmt(m.porosity * ph.fluid.thermal_conductivity)} W/m/K)",
                "check the value: it is the conductivity of the saturated rock, not of the grains")
        if proc in ("TH", "HC") and m.specific_storage:
            err("unverified_parameter", f"region '{r}': hydraulic storage with {proc} is not covered by a verification "
                "case in v0.1", "remove specific_storage (the flow then adjusts at once, as in the verified cases)")
        if proc == "HC" and m.transverse_dispersivity:
            warn("unverified_parameter", f"region '{r}': transverse dispersion is computed by OpenGeoSys but no "
                 "verification case observes it", "treat sideways spreading as an estimate")
        if proc in ("TM", "THM") and m.thermal_expansion is None:
            warn("default_value", f"region '{r}': no thermal_expansion given, so 0 is used (no thermal stress)",
                 "give thermal_expansion (linear, typical 5e-6 to 1.5e-5 1/K for rock)")
        if proc in ("HM", "THM") and m.biot_coefficient is None:
            warn("default_value", f"region '{r}': no biot_coefficient given, so 1 is used")
        if proc in ("HM", "THM") and m.specific_storage is not None:
            warn("ignored_value", f"region '{r}': specific_storage is not used with mechanics in v0.1: water is "
                 "incompressible, and the grain storage follows from the Biot coefficient, (alpha - phi)(1 - alpha)/K",
                 "remove it; set biot_coefficient below 1 for compressible grains")
        if proc == "H" and model.study.kind == "transient" and m.specific_storage is None:
            err("missing_property", f"region '{r}' needs specific_storage for transient flow",
                "give specific_storage (typical 1e-6 to 1e-4 1/m)")
        if proc == "HC" and m.longitudinal_dispersivity is None:
            warn("default_value", f"region '{r}': no dispersivity given, so 0 is used (diffusion only)",
                 "give longitudinal_dispersivity if mechanical dispersion matters")
        for prop, (lo, hi, unit) in PLAUSIBLE.items():
            v = getattr(m, prop, None)
            if v is not None and not lo <= v <= hi:
                warn("unusual_value", f"region '{r}': {prop} = {_fmt(v)} {unit} is outside the usual range "
                     f"{_fmt(lo)} to {_fmt(hi)} {unit}", "check the value and its unit")

    # physics
    if proc == "HC" and len(ph.components) != 1:
        err("missing_component", "transport needs exactly one component", "use set_physics with a component")
    if proc != "HC" and ph.components:
        err("unused_component", "components are only used with transport (HC)", "remove the component")
    if ph.fluid.density_increase_per_concentration > 0:
        if proc != "HC":
            err("density_coupling", "concentration-dependent density is only used with transport (HC)",
                "set density_increase_per_concentration to 0")
        elif not model.gravity_on:
            warn("density_without_gravity", "density depends on concentration but gravity is off, so there is no "
                 "buoyancy", "use a vertical section with gravity")
    if ph.gravity and vertical_axis(g) is None:
        warn("gravity_ignored", "gravity is ignored in a plan-view (horizontal) model")
    if proc in MECHANICS and model.gravity_on:
        err("gravity_with_mechanics", "gravity with mechanics needs an initial stress state, which v0.1 does not "
            "set up. " + configs.CONTACT, "use set_physics with gravity false")

    # boundary conditions
    bnames, inames = boundaries_of(g), interfaces_of(g)
    pnames_bc = [q for q in points_of(g) if q != "source"]
    allowed = VARIABLES[proc]
    seen, mech_seen = {}, {}
    for bc in model.boundary_conditions:
        if bc.boundary in inames:
            err("interface_condition", f"'{bc.boundary}' is an internal interface; conditions go on outer boundaries",
                f"use one of: {', '.join(bnames)}")
            continue
        if bc.boundary in pnames_bc:
            if bc.kind != "fixed" or bc.variable == "displacement":
                err("point_condition", f"'{bc.boundary}' is a point: only a fixed head, pressure, temperature or "
                    "concentration can be set there", "use a boundary for fluxes and mechanics")
                continue
        elif bc.boundary not in bnames:
            err("unknown_boundary", f"boundary '{bc.boundary}' does not exist (boundaries: {', '.join(bnames)})."
                + _closest(bc.boundary, bnames), "use one of the listed boundary names")
            continue
        if bc.variable not in allowed:
            err("wrong_variable", f"'{bc.variable}' is not a variable of process {proc} (variables: {', '.join(allowed)})",
                "use set_conditions with one of the listed variables")
            continue
        fam = "water" if bc.variable in ("head", "pressure") else bc.variable
        key = (bc.boundary, fam) if fam != "displacement" else (bc.boundary, fam, bc.kind, bc.component)
        if key in seen:
            err("duplicate_condition", f"boundary '{bc.boundary}' has two {fam} conditions", "keep one")
        seen[key] = bc
        if fam == "displacement":
            ax, _ = boundary_normal(g, bc.boundary)
            comps = ({ax} if bc.kind in ("roller", "load") else
                     {0, 1} if bc.component is None else {{"x": 0, "r": 0, "y": 1, "z": 1}[bc.component]})
            for c in comps:
                prev = mech_seen.get((bc.boundary, c))
                if prev is not None:
                    err("conflicting_condition", f"boundary '{bc.boundary}' has two displacement conditions on the same "
                        f"component ({prev.kind} and {bc.kind})", "keep one")
                mech_seen[(bc.boundary, c)] = bc
        if fam == "concentration" and bc.kind in ("flux", "rate"):
            err("unverified_condition", f"solute inflow conditions are not verified in v0.1 ('{bc.boundary}')",
                "use a fixed concentration on the inflow boundary")
        if fam == "water" and bc.kind in ("flux", "rate") and proc == "TH":
            err("unverified_condition", f"water inflow conditions are not verified with heat transport in v0.1 "
                f"('{bc.boundary}')", "use fixed heads or pressures to drive the flow")
        if fam == "water" and bc.kind in ("flux", "rate") and proc in MECHANICS:
            err("unverified_condition", f"water inflow conditions are not verified with mechanics in v0.1 "
                f"('{bc.boundary}')", "use a fixed head or pressure, or a closed boundary")
    families = {"T": ["temperature"], "H": ["water"], "TH": ["temperature", "water"], "HC": ["water", "concentration"],
                "HM": ["water"], "TM": ["temperature"], "THM": ["temperature", "water"]}[proc]
    if proc in MECHANICS:
        issues.extend(_rigid_body(model))
    if model.study.kind == "steady":
        for fam in families:
            if not any(f == fam and bc.kind == "fixed" for (_, f, *_), bc in seen.items()):
                err("no_fixed_value", f"a steady {fam} problem needs a fixed {fam if fam != 'water' else 'head or pressure'} "
                    "on at least one boundary", "use set_conditions to fix a value on one boundary")
    if "water" in families and not any(f == "water" and bc.kind == "fixed" for (_, f, *_), bc in seen.items()):
        if proc in ("TH", "HC", "HM", "THM"):
            err("no_fixed_value", "flow needs a fixed head or pressure on at least one boundary",
                "use set_conditions to fix head on one boundary")
    if not model.boundary_conditions:
        err("no_conditions", "no boundary conditions are set", "use set_conditions")

    # initial values and sources
    ini = model.initial
    if proc in ("T", "TH", "TM", "THM") and ini.temperature is None:
        err("missing_initial", "initial temperature is missing", "use set_conditions with initial temperature")
    if proc in ("H", "TH", "HC", "HM", "THM") and ini.head is None and ini.pressure is None:
        err("missing_initial", "initial head (or pressure) is missing", "use set_conditions with initial head")
    if proc == "HC" and ini.concentration is None:
        warn("default_value", "initial concentration not given, so 0 is used")
    pnames = points_of(g)
    for hs in model.heat_sources:
        if proc not in ("T", "TH", "TM", "THM"):
            err("source_needs_heat", "heat sources need a thermal process")
        elif hs.region in pnames:
            if hs.kind != "power":
                err("point_source_kind", "a point source is given as total power (W)", "use kind 'power'")
            lam = min((m.thermal_conductivity for m in model.materials.values() if m.thermal_conductivity), default=None)
            if lam:
                warn("point_source", "a point source is singular: temperatures within about two elements of the "
                     "point are not meaningful; read results at least that far away")
        elif hs.region not in regions:
            err("unknown_region", f"heat source region '{hs.region}' does not exist (regions: {', '.join(regions + pnames)})."
                + _closest(hs.region, regions + pnames))

    # study
    st = model.study
    if st.kind == "transient" and st.end_time is None:
        err("missing_end_time", "a transient study needs end_time", "use set_study with end_time")
    else:
        try:
            dts, _ = time_steps(model)
            if st.kind == "transient" and st.first_step is None:
                warn("default_value", f"no first_step given: {len(dts)} equal steps of {_fmt(dts[0])} s are used")
        except TranslationError as e:
            err("too_many_steps", str(e), f"keep the number of steps below {MAX_STEPS}")

    # mesh
    if mesh_info is None:
        err("mesh_not_built", "the mesh has not been built for this model", "use build_mesh")
    else:
        if mesh_info.get("hash") != mesh_hash(model):
            err("mesh_outdated", "the model changed after the mesh was built", "use build_mesh again")
        if str(mesh_info.get("summary", {}).get("element_type", "")).startswith("Tri"):
            from .selftest import triangles_ok
            tri_ok, tri_note = triangles_ok()
            if not tri_ok:
                err("engine_triangles_failed", "the OpenGeoSys engine on this computer failed the triangle self-test "
                    f"({tri_note}), so results on triangle elements cannot be trusted here",
                    "use set_mesh with element 'quad' (rectangle shapes); shapes that need triangles cannot be "
                    "computed on this computer")
        rep = mesh_info.get("report", {})
        for i in rep.get("issues", []):
            issues.append(Issue(i["level"], "mesh_" + i["code"], i["message"], i["fix"]))
        if mesh_info.get("bundle") is not None:
            issues += _overlapping_conditions(model, mesh_info["bundle"])
        if not [i for i in issues if i.level == "error"]:
            issues += resolution_advice(model, mesh_info)
    ok = not any(i.level == "error" for i in issues)
    return {"ok": ok, "configuration": cfg.id if cfg else None,
            "verification_cases": list(cfg.cases) if cfg else [],
            "issues": [i.as_dict() for i in issues]}


def _overlapping_conditions(model: Model, bundle) -> list[Issue]:
    """Conditions of one variable on boundaries that share elements (a side and its named part): two inflows or loads
    would add up, and two different fixed values contradict each other."""
    def edges(name):
        m = bundle.boundaries.get(name)
        if m is None or "bulk_node_ids" not in m.point_data:
            return set()
        ids = np.asarray(m.point_data["bulk_node_ids"])
        return {frozenset(ids[c].tolist()) for c in m.cells_dict.get(next(iter(m.cells_dict)), [])} if m.n_cells else set()
    out, bcs = [], [b for b in model.boundary_conditions if b.boundary in bundle.boundaries]
    for i, a in enumerate(bcs):
        for b in bcs[i + 1:]:
            fa = "water" if a.variable in ("head", "pressure") else a.variable
            fb = "water" if b.variable in ("head", "pressure") else b.variable
            if fa != fb or a.boundary == b.boundary:
                continue
            if fa == "displacement" and not (a.kind == b.kind == "load"):
                continue
            shared = edges(a.boundary) & edges(b.boundary)
            if not shared:
                continue
            if a.kind == b.kind == "fixed" and a.variable == b.variable and abs(a.value - b.value) <= 1e-12 * max(1.0, abs(a.value)):
                continue
            out.append(Issue("error", "overlapping_conditions",
                             f"the {fa} conditions on '{a.boundary}' and '{b.boundary}' apply to the same "
                             f"{len(shared)} boundary elements ({a.kind} and {b.kind}), so they would "
                             + ("add up" if "fixed" not in (a.kind, b.kind) else "contradict each other"),
                             f"keep one of them, or set the condition on the separate parts only"))
    return out


def _rigid_body(model: Model) -> list[Issue]:
    """2D: displacements must be held in x and y, and rotation prevented."""
    g = model.geometry
    held = {0: [], 1: []}   # axis -> boundaries holding that component
    for bc in model.boundary_conditions:
        if bc.variable != "displacement":
            continue
        ax, _ = boundary_normal(g, bc.boundary)
        if bc.kind == "roller":
            held[ax].append(bc.boundary)
        elif bc.kind == "fixed":
            comps = [0, 1] if bc.component is None else [{"x": 0, "r": 0, "y": 1, "z": 1}[bc.component]]
            for c in comps:
                held[c].append(bc.boundary + ("*" if bc.component is None else ""))
    if g.kind == "axisym_source" and not any(bc.boundary == "axis" and bc.variable == "displacement"
                                             for bc in model.boundary_conditions):
        held[0].append("axis")  # the translator applies u_r = 0 on the axis
    out = []
    names = {0: "r" if is_axisymmetric(g) else "x", 1: "z" if is_axisymmetric(g) else "y"}
    for c in (0, 1):
        if not held[c]:
            out.append(Issue("error", "rigid_body", f"nothing holds the model in {names[c]}: it could move freely",
                             f"add a roller on a boundary facing {names[c]} (e.g. "
                             f"{'left' if c == 0 else 'bottom'}) or fix the {names[c]} displacement"))
    if not out and not is_axisymmetric(g):
        fixed_all = [b for b in held[0] + held[1] if b.endswith("*")]
        # rotation: rollers only on one boundary in each direction are fine if those boundaries differ in direction
        if not fixed_all and len(set(held[0])) == 1 and len(set(held[1])) == 1 and held[0][0] == held[1][0]:
            out.append(Issue("error", "rigid_body", "the model could rotate", "hold a second boundary"))
    return out


def mesh_hash(model: Model) -> str:
    """The parts of the model that decide the mesh: geometry, mesh settings, element order."""
    import hashlib
    import json

    from .mesh import element_order
    d = {"g": model.geometry.model_dump(mode="json"), "m": model.mesh.model_dump(mode="json"),
         "o": element_order(model)}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def _darcy_estimate(model: Model) -> float | None:
    """Rough Darcy flux (m/s) from the flow conditions, for resolution advice."""
    f = model.physics.fluid
    ks = []
    for m in model.materials.values():
        if m.hydraulic_conductivity is not None:
            ks.append(m.hydraulic_conductivity)
        elif m.permeability is not None:
            ks.append(m.permeability * f.density * G / f.viscosity)
    fluxes = [abs(bc.value) for bc in model.boundary_conditions
              if bc.variable in ("head", "pressure") and bc.kind == "flux"]
    if fluxes:
        return max(fluxes)
    heads = [bc.value if bc.variable == "head" else bc.value / (f.density * G)
             for bc in model.boundary_conditions if bc.variable in ("head", "pressure") and bc.kind == "fixed"]
    if len(heads) >= 2 and ks:
        L = max(extents(model).values())
        return max(ks) * (max(heads) - min(heads)) / L
    return None


def resolution_advice(model: Model, mesh_info: dict) -> list[Issue]:
    out = []
    h = mesh_info.get("size_max")
    proc, st = model.physics.process, model.study
    if not h:
        return out
    q = _darcy_estimate(model) if proc in ("TH", "HC") else None
    dtmax = None
    if st.kind == "transient":
        dts, _ = time_steps(model)
        dtmax = max(dts)
    if proc == "HC" and q:
        comp = model.physics.components[0]
        for r, m in model.materials.items():
            if not m.porosity:
                continue
            v = q / m.porosity
            D = comp.pore_diffusion + (m.longitudinal_dispersivity or 0.0) * v
            pe = v * h / (2 * D) if D > 0 else math.inf
            if pe > 1:
                out.append(Issue("warning", "cell_peclet", f"region '{r}': cell Peclet number {pe:.2g} > 1 "
                                 "(the front will smear or oscillate)", f"use an element size below {_fmt(2 * D / v)} m"))
            if dtmax and v * dtmax / h > 1:
                out.append(Issue("warning", "courant", f"region '{r}': the front moves {v * dtmax / h:.2g} elements "
                                 "per time step", f"use max_step below {_fmt(h / v)} s"))
    if proc == "TH" and q:
        f = model.physics.fluid
        for r, m in model.materials.items():
            if m.thermal_conductivity:
                pe = f.density * f.specific_heat * q * h / (2 * m.thermal_conductivity)
                if pe > 1:
                    out.append(Issue("warning", "cell_peclet", f"region '{r}': thermal cell Peclet number {pe:.2g} > 1",
                                     f"use an element size below {_fmt(2 * m.thermal_conductivity / (f.density * f.specific_heat * q))} m"))
    g = model.geometry
    if g.kind == "axisym_source" and getattr(g, "source", None) == "point" and st.kind == "transient" \
            and model.heat_sources:
        first_out = min(st.output_times or [st.end_time])
        f = model.physics.fluid
        kappas = []
        for mm in model.materials.values():
            if mm.thermal_conductivity and mm.porosity is not None and mm.solid_density and mm.solid_specific_heat:
                rc = mm.porosity * f.density * f.specific_heat + (1 - mm.porosity) * mm.solid_density * mm.solid_specific_heat
                kappas.append(mm.thermal_conductivity / rc)
            elif mm.thermal_conductivity and mm.density and mm.specific_heat:
                kappas.append(mm.thermal_conductivity / (mm.density * mm.specific_heat))
        hs = [r.size for r in model.mesh.refinements if r.target == "source"]
        hsrc = min(hs) if hs else (model.mesh.size or h)
        if kappas:
            ell = math.sqrt(min(kappas) * first_out)
            # results/point_source_sweep.json: at 0.5 m the pore pressure is 6 % low for h = ell/4, 3 % for ell/8
            # (the V5 tolerance) and 0.8 % for the 0.01 m of the example and V5 (ell/12)
            if hsrc > ell / 8:
                out.append(Issue("error", "source_resolution",
                                 f"at the first output ({_fmt(first_out)} s) heat has spread only about {_fmt(ell)} m "
                                 f"from the point source, less than eight elements there ({_fmt(hsrc)} m); the "
                                 "temperature, pressure and stress near the source would be wrong",
                                 f"use set_mesh with a refinement at 'source' of about {_fmt(ell / 12)} m"))
    if proc in ("T", "TH") and st.kind == "transient":
        first_out = min(st.output_times or [st.end_time])
        for bc in model.boundary_conditions:
            if bc.variable != "temperature" or bc.kind != "fixed" or model.initial.temperature is None:
                continue
            if abs(bc.value - model.initial.temperature) < 1e-12:
                continue
            kappas = []
            for mm in model.materials.values():
                rc = None
                if mm.density and mm.specific_heat:
                    rc = mm.density * mm.specific_heat
                elif mm.porosity and mm.solid_density and mm.solid_specific_heat:
                    f = model.physics.fluid
                    rc = mm.porosity * f.density * f.specific_heat + (1 - mm.porosity) * mm.solid_density * mm.solid_specific_heat
                if rc and mm.thermal_conductivity:
                    kappas.append(mm.thermal_conductivity / rc)
            if not kappas:
                continue
            ell = math.sqrt(min(kappas) * first_out)
            hb = mesh_info.get("boundary_sizes", {}).get(bc.boundary)
            if hb and hb > ell / 2:
                out.append(Issue("warning", "front_resolution",
                                 f"at the first output ({_fmt(first_out)} s) heat has spread about {_fmt(ell)} m from "
                                 f"'{bc.boundary}', which is less than two elements ({_fmt(hb)} m)",
                                 f"refine near '{bc.boundary}' to about {_fmt(ell / 4)} m, or output later"))
        if st.end_time:
            reach = math.sqrt(max([mm.thermal_conductivity / (mm.density * mm.specific_heat)
                                   for mm in model.materials.values()
                                   if mm.thermal_conductivity and mm.density and mm.specific_heat] or [0]) * st.end_time)
            L = max(extents(model).values())
            if reach > 0.5 * L:
                out.append(Issue("warning", "domain_reach", f"by the end time heat spreads about {_fmt(reach)} m, more "
                                 f"than half the model size ({_fmt(L)} m); the outer boundaries may affect the result",
                                 "enlarge the model or shorten the study if the boundaries should not matter"))
    return out


def _val(variable: str, v: float, kind: str = "fixed") -> str:
    if variable == "temperature":
        return {"fixed": f"{v - 273.15:.4g} °C", "flux": f"{v:.4g} W/m2", "rate": f"{v:.4g} W"}.get(kind, f"{v:.4g}")
    return f"{v:.4g}"


def tree_summary(model: Model | None, mesh_summary: dict | None = None, max_len: int = 900) -> str:
    if model is None:
        return "empty model"
    g = model.geometry
    ext = extents(model)
    parts = [f"geometry {g.kind} " + " x ".join(f"{_fmt(v)} m" for v in ext.values())
             + f" ({', '.join(ext)}), regions {', '.join(regions_of(g))}"]
    parts.append(f"physics {model.physics.process}" + (", gravity on" if model.gravity_on else ""))
    done = [r for r in regions_of(g) if r in model.materials]
    parts.append(f"materials {len(done)}/{len(regions_of(g))} regions")
    units = {"head": " m", "pressure": " Pa", "concentration": "", "temperature": ""}
    bcs = "; ".join(f"{bc.boundary}: {bc.variable} {bc.kind} {_val(bc.variable, bc.value, bc.kind)}"
                    + (units[bc.variable] if bc.kind == "fixed" else "") for bc in model.boundary_conditions)
    parts.append(f"conditions {bcs or 'none'}")
    if model.heat_sources:
        parts.append("heat sources " + "; ".join(f"{h.region} {_fmt(h.value)} {'W' if h.kind == 'power' else 'W/m3'}"
                                                 for h in model.heat_sources))
    parts.append("mesh " + (f"{mesh_summary['elements']} {mesh_summary['element_type']}" if mesh_summary else "not built"))
    st = model.study
    if st.kind == "steady":
        parts.append("study steady")
    elif st.end_time:
        parts.append(f"study transient to {_fmt(st.end_time / YEAR) + ' yr' if st.end_time >= YEAR else _fmt(st.end_time) + ' s'}")
    else:
        parts.append("study not set")
    s = " | ".join(parts)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."
