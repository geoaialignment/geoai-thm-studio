"""Verification cases (L2): build each case from its model tree, run OGS, compare with the reference.

A case file (cases/<id>.json) fixes the model, the reference solution, the
observed quantity, where and when it is observed, how errors are normalised,
and the tolerance. 'official' cases run an official OGS input unchanged and
compare its output with the same reference.
"""
from __future__ import annotations

import json
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import analytic as an
from .mesh import build_mesh
from .post import Results
from .runner import run_ogs
from .schema import Model
from .translator import translate

import os

PKG = Path(__file__).resolve().parent
ROOT = PKG.parents[1]                      # the source tree, when run from it
CASES = PKG / "cases"
USER = Path(os.environ.get("THMSTUDIO_HOME", Path.home() / ".thmstudio"))
REFERENCES = Path(os.environ.get("THMSTUDIO_OGS_TESTDATA", ROOT / "references" / "ogs-6.5.8"))
SOLVER = "auto"  # 'direct' or 'iterative' to verify the linear-solver presets


def _coord(points: np.ndarray, ref: dict) -> np.ndarray:
    """Coordinate the 1D reference uses: distance along an axis, or radius from a centre."""
    if "center" in ref:
        c = np.asarray(ref["center"], float)
        return np.linalg.norm(points[:, : len(c)] - c, axis=1)
    ax = ref.get("axis", 0)
    return ref.get("sign", 1.0) * (points[:, ax] - ref.get("origin", 0.0))


def reference_values(ref: dict, points: np.ndarray, t: float) -> np.ndarray:
    s = _coord(points, ref)
    p, base = ref.get("params", {}), ref.get("base", 0.0)
    kind = ref["type"]
    if kind == "constant":
        return np.full(len(points), base + ref.get("value", 0.0))
    if kind == "linear_in":  # value = base + slope * s
        return base + ref["slope"] * s
    if kind == "erfc_step":
        return base + an.erfc_step(s, t, p["diffusivity"], p.get("dT", 1.0))
    if kind == "slab_with_source":
        return base + an.slab_with_source(s, p["length"], p["q"], p["conductivity"])
    if kind == "series_layers":
        return an.series_layers(s, p["bounds"], p["conductivities"], p["v0"], p["v1"])
    if kind == "theis_head":
        return base - an.theis_drawdown(s, t, p["rate"], p["transmissivity"], p["storativity"])
    if kind == "radial_inclusion":
        return an.radial_inclusion(s, p["a"], p["q"], p["k_in"], p["k_out"], p["r_ref"], p["t_ref"])
    if kind == "advection_dispersion":
        return base + an.advection_dispersion(s, t, p["v"], p["D"], p.get("R", 1.0), p.get("decay", 0.0),
                                              p.get("c0", 1.0))
    if kind == "heat_advection":
        return base + an.heat_advection(s, t, p["darcy_velocity"], p["rho_c_eff"], p["rho_c_water"],
                                        p["conductivity"], p.get("dT", 1.0))
    if kind == "terzaghi_pressure":
        return an.terzaghi_pressure(s, t, p["load"], p["cv"], p["H"])
    if kind == "terzaghi_settlement":  # displacement of the top (negative = down)
        return np.full(len(points), -an.terzaghi_settlement(t, p["load"], p["cv"], p["H"], p["M"]))
    if kind == "biot_settlement":
        return np.full(len(points), an.biot_settlement(t, p["load"], p["alpha"], p["p0"], p["cv"], p["H"], p["M"]))
    if kind == "point_heat_source":
        src = an.PointHeatSource(**p)
        return {"temperature": src.temperature, "pressure": src.pressure,
                "radial_displacement": src.radial_displacement}[ref["quantity"]](s, t)
    if kind == "official_field":  # a field of an official OGS output, sampled at the same physical points
        import pyvista as pv
        m = pv.read(REFERENCES / ref["file"])
        off = np.asarray(ref.get("offset", [0.0, 0.0, 0.0]), float)
        pts = np.zeros((len(points), 3))
        for i, ax in enumerate(ref.get("axes", [0, 1, 2])[: points.shape[1]]):
            pts[:, ax] = points[:, i]
        pts += off
        smp = pv.PolyData(pts).sample(m)
        return np.asarray(smp.point_data[ref["field"]])
    if kind == "uniform_strain":  # u = strain * (x - origin) along an axis
        return ref["strain"] * s
    raise KeyError(f"unknown reference type {kind}")


def observation_points(obs: dict) -> np.ndarray:
    if "points" in obs:
        return np.asarray(obs["points"], float)
    ln = obs["line"]
    a, b = np.asarray(ln["from"], float), np.asarray(ln["to"], float)
    s = np.linspace(0, 1, ln.get("n", 51))
    return a[None, :] + s[:, None] * (b - a)[None, :]


@dataclass
class CaseResult:
    id: str
    passed: bool | None  # None: skipped
    seconds: float
    checks: list[dict] = field(default_factory=list)
    run: dict = field(default_factory=dict)
    mesh: dict = field(default_factory=dict)
    note: str = ""

    def as_dict(self):
        return self.__dict__


def compare(sim: np.ndarray, ref: np.ndarray, norm: dict, tol: dict, base: float) -> dict:
    err = sim - ref
    kind = norm.get("type", "scale")
    if kind == "relative":
        e = np.abs(err) / np.maximum(np.abs(ref - base), 1e-300)
    elif kind == "max":  # largest reference change along the observation
        e = np.abs(err) / max(float(np.abs(ref - base).max()), 1e-300)
    else:
        e = np.abs(err) / norm.get("scale", 1.0)
    den = np.linalg.norm(ref - base)
    den = den if den > 0 else np.linalg.norm(ref)
    # relative L2 error; when the reference is zero (a stress that must vanish) the absolute norm divided by the scale
    l2 = float(np.linalg.norm(err) / den) if den > 1e-12 * max(norm.get("scale", 1.0), 1e-300) else \
        float(np.linalg.norm(err) / max(norm.get("scale", 1.0), 1e-300))
    out = {"max_norm_error": float(e.max()), "l2_rel_error": l2, "n": int(len(sim))}
    ok = True
    if "max_norm" in tol:
        ok &= out["max_norm_error"] <= tol["max_norm"]
    if "l2_rel" in tol:
        ok &= l2 <= tol["l2_rel"]
    out["passed"] = bool(ok)
    return out


def _field(res: Results, t: float, obs: dict, pts: np.ndarray) -> np.ndarray:
    name = obs["field"]
    if "component" in obs:
        m = res.mesh_at(t).copy()
        m.point_data["_c"] = np.asarray(m.point_data[name])[:, obs["component"]]
        import pyvista as pv
        s = pv.PolyData(np.c_[pts, np.zeros(len(pts))] if pts.shape[1] == 2 else pts).sample(m)
        return np.asarray(s.point_data["_c"])
    return res.at_points(t, name, pts)


def run_case(case: dict, workdir: Path, size_factor: float = 1.0) -> CaseResult:
    t0 = time.time()
    if case.get("kind") == "official":
        return _run_official(case, workdir, t0)
    model = Model.model_validate(case["model"])
    if size_factor != 1.0:
        ms = model.mesh.model_copy(deep=True)
        if ms.size:
            ms.size *= size_factor
        ms.divisions = {k: max(1, int(round(v / size_factor))) for k, v in ms.divisions.items()}
        for r in ms.refinements:  # refine near the target and away from it
            r.size *= size_factor
            r.growth = min(2.0, 1.0 + (r.growth - 1.0) * size_factor)
        st = model.study.model_copy()
        if st.kind == "transient":  # scale time with space: backward Euler is first order in time
            st.first_step = (st.first_step or st.end_time / 100.0) * size_factor
            st.growth = min(2.0, 1.0 + (st.growth - 1.0) * size_factor)
            if st.max_step:
                st.max_step *= size_factor
        model = model.model_copy(update={"mesh": ms, "study": st})
    shutil.rmtree(workdir, ignore_errors=True)
    bundle, qrep = build_mesh(model, workdir / "build")
    if not qrep.ok:
        return CaseResult(case["id"], False, time.time() - t0, mesh=qrep.as_dict(), note="mesh check failed")
    br = translate(model, bundle, workdir / "build", solver=SOLVER)
    rec = run_ogs(br.prj, workdir / "run", br.t_end, expected_fields=br.primary, output_times=br.output_times)
    res = CaseResult(case["id"], False, 0.0, run=rec.as_dict(), mesh=bundle.summary())
    if rec.status != "succeeded":
        res.note = f"run failed: {rec.failure}"
        res.seconds = time.time() - t0
        return res
    results = Results.load(workdir / "run", model)
    res.checks = _checks(case, results, br.output_times)
    if "convergence" in case and size_factor == 1.0:
        res.checks += _convergence(case, results, workdir)
    res.passed = all(c["passed"] for c in res.checks)
    res.seconds = round(time.time() - t0, 2)
    return res


def _convergence(case, results, workdir):
    """Same model with twice the element size and time step: the change bounds the error of the base model
    (for first-order time stepping the base error is about the change itself, less for space)."""
    fine = run_case({k: v for k, v in case.items() if k != "convergence"}, workdir.parent / f"{workdir.name}_conv", 2.0)
    if fine.run.get("status") != "succeeded":
        return [{"label": "mesh and time-step convergence", "passed": False, "max_norm_error": float("inf"),
                 "l2_rel_error": float("inf"), "n": 0, "field": "", "time": 0.0, "note": fine.note}]
    rf = Results.load(Path(fine.run["rundir"]), Model.model_validate(case["model"]))
    out = []
    for c in case["convergence"]:
        pts = np.asarray(c["points"], float)
        t = float(results.times[np.argmin(np.abs(results.times - c["time"]))])
        a = results.at_points(t, c["field"], pts)
        b = rf.at_points(float(rf.times[np.argmin(np.abs(rf.times - t))]), c["field"], pts)
        base = c.get("base", 0.0)
        rel = float(np.max(np.abs(a - b)) / max(np.max(np.abs(b - base)), 1e-300))
        out.append({"field": c["field"], "time": t, "label": c["label"], "max_norm_error": rel, "l2_rel_error": rel,
                    "n": len(pts), "passed": rel <= c["max_rel_change"], "coarse": a.tolist(), "fine": b.tolist()})
    return out


def heat_content(results, t: float) -> float:
    """Heat stored relative to the initial temperature: sum over cells of (rho c)_eff dT dV (axisymmetric: 2 pi r)."""
    import math
    model = results.model
    m = results.mesh_at(t).copy()
    T = results.field(m, "temperature") - model.initial.temperature
    m.point_data["_dT"] = T
    c = m.point_data_to_cell_data()
    dT = np.asarray(c.cell_data["_dT"])
    sizes = np.abs(np.asarray(m.compute_cell_sizes(length=False, area=True, volume=True).cell_data[
        "Volume" if np.ptp(m.points[:, 2]) > 0 else "Area"]))
    if model.geometry.kind in ("axisym_well", "axisym_source"):
        sizes = sizes * 2 * math.pi * m.cell_centers().points[:, 0]
    f = model.physics.fluid
    mats = np.asarray(m.cell_data["MaterialIDs"])
    from .schema import regions_of
    rc = []
    for r in regions_of(model.geometry):
        mm = model.materials[r]
        if mm.porosity is not None and mm.solid_density is not None:
            rc.append(mm.porosity * f.density * f.specific_heat + (1 - mm.porosity) * mm.solid_density * mm.solid_specific_heat)
        else:
            rc.append(mm.density * mm.specific_heat)
    return float(np.sum(np.asarray(rc)[mats] * dT * sizes))


def _checks(case, results, output_times):
    out = []
    for obs in case.get("integrals", []):
        t = float(results.times[np.argmin(np.abs(results.times - obs["time"]))])
        got = heat_content(results, t)
        exp = obs["power"] * t * obs.get("fraction", 1.0)
        rel = abs(got - exp) / abs(exp)
        out.append({"field": "heat_content", "time": t, "label": obs["label"], "max_norm_error": rel,
                    "l2_rel_error": rel, "n": 1, "passed": rel <= obs["tolerance"], "value": got, "expected": exp})
    for obs in case["observations"]:
        pts = observation_points(obs)
        want = obs.get("time", output_times[-1])
        t = float(results.times[np.argmin(np.abs(results.times - want))])
        if abs(t - want) > 1e-6 * max(abs(want), 1.0):  # no output at the requested time: fail, never substitute
            out.append({"field": obs["field"], "time": want, "label": obs.get("label", ""), "passed": False,
                        "max_norm_error": float("inf"), "l2_rel_error": float("inf"), "n": 0,
                        "note": f"no output at t = {want:g} s (nearest {t:g} s)"})
            continue
        sim = _field(results, t, obs, pts)
        ref = reference_values(obs.get("reference", case["reference"]), pts, t)
        base = obs.get("reference", case["reference"]).get("base", 0.0)
        c = compare(sim, ref, obs.get("normalization", case.get("normalization", {})),
                    obs.get("tolerance", case["tolerance"]), base)
        c.update({"field": obs["field"], "time": t, "label": obs.get("label", "")})
        out.append(c)
    return out


def _run_official(case: dict, workdir: Path, t0: float) -> CaseResult:
    src = REFERENCES / case["official"]
    if not src.exists():
        return CaseResult(case["id"], None, 0.0, note="skipped: OGS test data not found (set THMSTUDIO_OGS_TESTDATA)")
    shutil.rmtree(workdir, ignore_errors=True)
    shutil.copytree(src.parent, workdir / "build")
    prj = workdir / "build" / src.name
    rec = run_ogs(prj, workdir / "run", case["t_end"])
    res = CaseResult(case["id"], False, 0.0, run=rec.as_dict())
    if rec.status != "succeeded":
        res.note = f"run failed: {rec.failure}"
        return res
    model = Model.model_validate(case["model"]) if "model" in case else None
    results = Results.load(workdir / "run", model)
    res.checks = _checks(case, results, [t for t, _ in results.outputs])
    res.passed = all(c["passed"] for c in res.checks)
    res.seconds = round(time.time() - t0, 2)
    return res


def load_cases(ids: list[str] | None = None) -> list[dict]:
    cases = [json.loads(p.read_text()) for p in sorted(CASES.glob("*.json"))]
    return [c for c in cases if ids is None or c["id"] in ids]


def versions() -> dict:
    """The package and engine a result was computed with; a result from other versions is not evidence for this one."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        pkg = version("geoai-thm-studio")
    except PackageNotFoundError:
        pkg = "unknown"
    return {"package_version": pkg, "ogs_version": version("ogs")}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="run verification cases")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--work", default=str(USER / "verify_work"))
    ap.add_argument("--refine", action="store_true", help="also run with half the element size and time step")
    ap.add_argument("--out", default=str(USER / "verification.json"))
    ap.add_argument("--solver", default="auto", choices=["auto", "direct", "iterative"])
    a = ap.parse_args(argv)
    global SOLVER
    SOLVER = a.solver
    known = {c["id"] for c in load_cases()}
    unknown = [i for i in a.ids if i not in known]
    if unknown:
        print(f"unknown case id: {', '.join(unknown)} (cases: {', '.join(sorted(known))})")
        return 2
    rows, ok = [], True
    for case in load_cases(a.ids or None):
        r = run_case(case, Path(a.work) / case["id"])
        row = r.as_dict()
        if a.refine and case.get("kind") != "official":
            r2 = run_case(case, Path(a.work) / f"{case['id']}_h2", 0.5)
            row["refined"] = {"checks": r2.checks, "mesh": r2.mesh, "passed": r2.passed}
            ok &= r2.passed is not False
        ok &= r.passed is not False
        rows.append(row)
        worst = max((c["max_norm_error"] for c in r.checks), default=float("nan"))
        print(f"{case['id']:14s} {'SKIP' if r.passed is None else 'PASS' if r.passed else 'FAIL'} {r.seconds:7.1f}s  worst norm. error {worst:.2e}"
              + (f"  (h/2: {max(c['max_norm_error'] for c in row['refined']['checks']):.2e})"
                 if a.refine and row.get('refined', {}).get('checks') else "") + (f"  {r.note}" if r.note else ""))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    merged = {}
    if Path(a.out).exists():  # keep results of cases not run this time
        try:
            merged = {r["id"]: r for r in json.loads(Path(a.out).read_text())}
        except ValueError:
            merged = {}
    for r in rows:
        if r["passed"] is None:
            continue  # a skipped case keeps its earlier result, which counts only if its versions match
        r["date"] = time.strftime("%Y-%m-%d %H:%M")
        r.update(versions())
        merged[r["id"]] = r
    Path(a.out).write_text(json.dumps([merged[k] for k in sorted(merged)], indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
