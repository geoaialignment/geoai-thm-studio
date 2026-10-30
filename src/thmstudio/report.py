"""answer_card, verification status, the output guardrail and the results page.

The card is computed and rendered by the program. A final answer may only quote numbers
that appear on the card or in the user's own model inputs; the guardrail finds the others.
"""
from __future__ import annotations

import base64
import html
import json
import math
import re
import time
from pathlib import Path

import numpy as np

from . import configs
from .post import Results
from .schema import BoundaryCondition, Model
from .units import YEAR

import os

RECORD = Path(__file__).resolve().parent / "verification_record.json"   # results shipped with the release
USER_RESULTS = Path(os.environ.get("THMSTUDIO_HOME", Path.home() / ".thmstudio")) / "verification.json"

DISPLAY = {  # field -> (SI unit, display unit, factor, offset)
    "temperature": ("K", "°C", 1.0, -273.15), "pressure": ("Pa", "MPa", 1e-6, 0.0), "head": ("m", "m", 1.0, 0.0),
    "displacement": ("m", "mm", 1e3, 0.0), "sigma": ("Pa", "MPa", 1e-6, 0.0), "darcy_velocity": ("m/s", "m/s", 1.0, 0.0),
    "heat_flux": ("W/m2", "W/m2", 1.0, 0.0), "epsilon": ("-", "-", 1.0, 0.0),
}


def display(field: str, v: float) -> tuple[float, str, str]:
    si, du, f, o = DISPLAY.get(field, ("-", "-", 1.0, 0.0))
    return v * f + o, du, si


def fmt(v: float, sig: int = 3) -> str:
    if v == 0 or not math.isfinite(v):
        return f"{v:g}"
    d = sig - int(math.floor(math.log10(abs(v)))) - 1
    return f"{round(v, d):.{max(d, 0)}f}" if -4 < math.log10(abs(v)) < 6 else f"{v:.{sig - 1}e}"


def time_text(t: float) -> str:
    if t >= YEAR:
        return f"{fmt(t / YEAR)} yr"
    if t >= 86400:
        return f"{fmt(t / 86400)} d"
    return f"{fmt(t)} s"


# ---------------------------------------------------------------- verification status

def verification_status(model: Model) -> dict:
    g = model.geometry
    cfg = configs.find(model.physics.process, g.kind, getattr(g, "source", None),
                       buoyant=model.physics.fluid.density_increase_per_concentration > 0)
    if cfg is None:
        return {"configuration": None, "cases": [], "note": "not a verified configuration"}
    rows = []
    results, source = {}, {}
    for path, label in ((RECORD, "release record"), (USER_RESULTS, "this installation")):  # later wins per case
        try:
            for r in json.loads(path.read_text()):
                results[r["id"]], source[r["id"]] = r, label
        except (OSError, ValueError):
            continue
    from .verify import versions
    now = versions()
    for cid in cfg.cases:
        r = results.get(cid)
        if r is None:
            rows.append({"case": cid, "status": "not checked"})
            continue
        worst = max((c["max_norm_error"] for c in r["checks"]), default=float("nan"))
        status = "passed" if r["passed"] else "FAILED"
        if any(r.get(k) != v for k, v in now.items()):
            status = f"outdated (computed with {r.get('package_version', 'an earlier version')})"
        rows.append({"case": cid, "status": status, "worst_normalised_error": worst,
                     "source": source[cid], "date": r.get("date", "")})
    return {"configuration": cfg.id, "title": cfg.title, "demonstration": cfg.demonstration, "cases": rows}


def run_checks(rundir: Path, rec: dict) -> dict:
    """Checks on this run: end time, finite values, rejected steps, nonlinear iterations."""
    out = {"reached_end_time": rec.get("reached_end", False), "finite_values": rec.get("finite", False)}
    log = Path(rundir) / "ogs.log"
    if log.exists():
        text = log.read_text(errors="replace")
        m = re.search(r"accepted steps are (\d+), and the rejected steps are (\d+)", text)
        if m:
            out["time_steps"], out["rejected_steps"] = int(m.group(1)), int(m.group(2))
        its = [int(x) for x in re.findall(r"Iteration #(\d+) started", text)]
        if its:
            out["max_nonlinear_iterations"] = max(its)
    out["energy_balance"] = "not checked"
    if rec.get("notes"):
        out["notes"] = "; ".join(rec["notes"])
    return out


def range_check(model: Model, res: Results) -> dict:
    """A temperature or concentration with only fixed values on its boundaries and no sources must stay between its
    smallest and largest initial or fixed value. Leaving that range by more than 1 % of it means the mesh or the time
    step is too coarse for the flow (numerical overshoot)."""
    out = {}
    comp = model.physics.components[0] if model.physics.components else None
    for var, name in (("temperature", "temperature"), ("concentration", comp.name if comp else None)):
        if name is None or (var == "temperature" and model.heat_sources):
            continue
        bcs = [b for b in model.boundary_conditions if b.variable == var]
        init = getattr(model.initial, var, None)
        if not bcs or any(b.kind != "fixed" for b in bcs) or init is None:
            continue
        lo, hi = min([init] + [b.value for b in bcs]), max([init] + [b.value for b in bcs])
        if hi - lo <= 0:
            continue
        try:
            vals = np.concatenate([res.field(res.mesh_at(t), name) for t in res.times])
        except KeyError:
            continue
        over = max(lo - float(vals.min()), float(vals.max()) - hi, 0.0) / (hi - lo)
        if over > 0.01:
            out[var] = (f"values reach {display(name, float(vals.min()))[0]:.3g} to {display(name, float(vals.max()))[0]:.3g}, "
                        f"outside the range of the initial and fixed values by {100 * over:.0f} %: the mesh or time step "
                        "is too coarse for this flow; use set_mesh with smaller elements and compare half_element_size")
    return out


# ---------------------------------------------------------------- the card

def make_card(model: Model, rec: dict, items: list[dict], comparisons: dict[str, dict] | None = None) -> dict:
    res = Results.load(Path(rec["rundir"]), model)
    probes = {p.name: p for p in model.probes}
    rows = []
    for it in items:
        kind = it.get("kind", "value")
        if kind == "comparison":
            c = (comparisons or {}).get(it["comparison"])
            if c is None:
                raise KeyError(f"no comparison '{it['comparison']}' has been run (run compare first)")
            fname = c["field"].split(" ")[0]
            si, du, f, _ = DISPLAY.get(fname, ("-", "-", 1.0, 0.0))
            v, du = c["max_abs_difference"] * f, ("K" if fname == "temperature" else du)  # a difference has no offset
            rows.append({"label": it.get("label") or f"largest change from {it['comparison']}", "quantity": c["field"],
                         "aggregation": "largest difference", "location": c["probe"], "time": time_text(c["time_s"]),
                         "value": fmt(v), "unit": du, "value_si": c["max_abs_difference"], "unit_si": si})
            continue
        field = it["field"]
        if it.get("component"):
            res.select_component(field, it["component"])
        if it.get("time_s") is None:
            t = res.times[-1]
        else:
            from .tools import output_time
            t = output_time(res.times, it["time_s"])
        loc_text = ""
        if kind in ("value", "change"):
            pt = it.get("point")
            if pt is None and it.get("probe") in probes and probes[it["probe"]].point:
                pt = probes[it["probe"]].point
                loc_text = f"{it['probe']} {tuple(round(float(x), 4) for x in pt)} m"
            if pt is None:
                raise KeyError("a value needs a point or a point probe")
            loc_text = loc_text or f"{tuple(round(float(x), 4) for x in pt)} m"
            val = res.at_points(t, field, np.atleast_2d(pt))
            val = float(np.linalg.norm(val[0]) if np.ndim(val) == 2 else val[0])
            if kind == "change":
                v0 = res.at_points(float(res.times[0]), field, np.atleast_2d(pt))
                val -= float(np.linalg.norm(v0[0]) if np.ndim(v0) == 2 else v0[0])
                si, du, f, _ = DISPLAY.get(field, ("-", "-", 1.0, 0.0))
                du = "K" if field == "temperature" else du
                rows.append({"label": it.get("label") or f"change of {field}",
                             "quantity": field + (f" ({it['component']})" if it.get("component") else ""),
                             "aggregation": "change since start",
                             "location": loc_text, "time": time_text(t), "value": fmt(val * f), "unit": du,
                             "value_si": val, "unit_si": si})
                continue
        else:
            if it.get("probe") in probes and probes[it["probe"]].line:
                ln = probes[it["probe"]].line
                _, vals = res.on_line(t, field, ln[0], ln[1], 201)
                loc_text = f"along {it['probe']}"
            else:
                vals = res.field(res.mesh_at(t), field)
                loc_text = "whole model"
            vals = np.linalg.norm(vals, axis=1) if np.ndim(vals) == 2 else vals
            val = float({"max": np.max, "min": np.min, "mean": np.mean}[kind](vals))
        v, du, si = display(field, val)
        rows.append({"label": it.get("label") or f"{kind} {field}", "quantity": field + (f" ({it['component']})" if it.get("component") else ""),
                     "aggregation": kind, "location": loc_text, "time": time_text(t), "value": fmt(v), "unit": du,
                     "value_si": val, "unit_si": si})
    card = {"run_id": rec["run_id"], "model_name": model.name,
            "created": time.strftime("%Y-%m-%d %H:%M"), "rows": rows,
            "verification": verification_status(model), "run_checks": run_checks(Path(rec["rundir"]), rec)}
    overshoot = range_check(model, res)
    if overshoot:
        card["run_checks"]["overshoot"] = overshoot
    card["table"] = render_table(card)
    return card


def render_table(card: dict) -> str:
    lines = [f"Results of run {card['run_id']} (model {card['model_name']})", "",
             "| quantity | where | when | how | value |", "|---|---|---|---|---|"]
    for r in card["rows"]:
        lines.append(f"| {r['label']} | {r['location']} | {r['time']} | {r['aggregation']} | {r['value']} {r['unit']} |")
    v = card["verification"]
    lines.append("")
    if v["configuration"]:
        cases = ", ".join(f"{c['case']} {c['status']}" + (f" (max error {fmt(100 * c['worst_normalised_error'], 2)} %)"
                                                           if "worst_normalised_error" in c else "") for c in v["cases"])
        lines.append(f"Verified configuration {v['configuration']}" + (" (demonstration)" if v.get("demonstration") else "")
                     + f": {cases}.")
    rc = {k: v for k, v in card["run_checks"].items() if k != "overshoot"}
    lines.append("This run: " + ", ".join(f"{k.replace('_', ' ')} {val}" for k, val in rc.items()) + ".")
    for var, text in card["run_checks"].get("overshoot", {}).items():
        lines.append(f"Warning ({var}): {text}.")
    return "\n".join(lines)


# ---------------------------------------------------------------- guardrail

# Latin letters and digits bound a number; Korean or other script may touch it ("10도", "50,000초")
_NUM = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_.])")


_VARIANTS = {  # how an input of each kind may be quoted
    "temperature": lambda x: [x, x - 273.15],
    "pressure": lambda x: [x, x / 1e3, x / 1e6, x / 1e9],
    "time": lambda x: [x, x / 3600, x / 86400, x / YEAR],
    "flow_rate": lambda x: [x, x * 86400, x * 1000],
    "velocity": lambda x: [x, x * 86400, x * YEAR],
    "length": lambda x: [x, x * 1e3, x * 1e2],
    "plain": lambda x: [x],
}
_KIND_OF_KEY = {"end_time": "time", "first_step": "time", "max_step": "time", "output_times": "time", "half_life": "time",
                "youngs_modulus": "pressure", "hydraulic_conductivity": "velocity", "temperature": "temperature",
                "pressure": "pressure", "width": "length", "thickness": "length", "height": "length",
                "length_x": "length", "length_y": "length", "radius": "length", "outer_radius": "length",
                "well_radius": "length", "size": "length", "start": "length", "end": "length", "center": "length",
                "point": "length", "line": "length", "head": "length"}
_DIM_OF_KIND = {"temperature": "temperature", "pressure": "pressure", "time": "time", "flow_rate": "flow_rate",
                "velocity": "velocity", "length": "length", "plain": "other"}
_DIM_OF_UNIT = {"K": "temperature", "°C": "temperature", "Pa": "pressure", "kPa": "pressure", "MPa": "pressure",
                "GPa": "pressure", "m": "length", "mm": "length", "cm": "length", "km": "length", "s": "time",
                "h": "time", "d": "time", "yr": "time", "m/s": "velocity", "m/d": "velocity", "m/yr": "velocity",
                "m3/s": "flow_rate", "m3/d": "flow_rate", "L/s": "flow_rate", "%": "percent"}


def allowed_entries(model: Model | None, cards: list[dict]) -> list[tuple[float, str | None]]:
    """Card values and the user's inputs with their dimension, in the units they may reasonably be quoted in."""
    vals: list[tuple[float, str | None]] = []
    for c in cards:
        for r in c["rows"]:
            dim = _DIM_OF_UNIT.get(r.get("unit", ""), "other")
            vals += [(float(r["value"]), dim), (r["value_si"], _DIM_OF_UNIT.get(r.get("unit_si", ""), "other")),
                     (100 * float(r["value"]), "percent")]
            vals += [(float(m.group(0)), "length") for m in _NUM.finditer(r.get("location", ""))]
            vals += [(float(m.group(0)), "time") for m in _NUM.finditer(r.get("time", ""))]
        for v in (c.get("run_checks") or {}).values():  # step counts and iterations, quoted as counts
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append((float(v), "seen"))
        for case in c["verification"]["cases"]:
            if "worst_normalised_error" in case:
                vals += [(case["worst_normalised_error"], "other"), (100 * case["worst_normalised_error"], "percent")]
    if model is None:
        return vals
    from pydantic import BaseModel

    def add(x, kind):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return
        kind = kind if kind in _VARIANTS else "plain"
        vals.extend((v, _DIM_OF_KIND.get(kind, "other")) for v in _VARIANTS[kind](float(x)))

    def walk(obj, kind="plain"):
        if isinstance(obj, BoundaryCondition):
            k = {"temperature": "temperature", "pressure": "pressure", "head": "length"}.get(obj.variable, "plain")
            if obj.kind == "load":
                k = "pressure"
            elif obj.kind == "rate":
                k = "flow_rate" if obj.variable in ("head", "pressure") else "plain"
            elif obj.kind == "flux":
                k = "velocity" if obj.variable in ("head", "pressure") else "plain"
            add(obj.value, k)
        elif isinstance(obj, BaseModel):
            for name, f in type(obj).model_fields.items():
                walk(getattr(obj, name), _field_kind(f, name))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v, kind)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v, kind)
        else:
            add(obj, kind)

    walk(model)
    return vals


def _field_kind(f, name: str) -> str:
    """The quoting kind of a model field, from its declared dimension (coordinates count as lengths)."""
    import typing
    from .units import Dim
    stack = [f.annotation] + list(f.metadata)
    while stack:
        t = stack.pop()
        if isinstance(t, Dim):
            return str(t)
        stack += [a for a in getattr(t, "__metadata__", ()) if isinstance(a, Dim)] + list(typing.get_args(t))
    return "length" if name in ("point", "line", "start", "end", "center", "from", "to") else "plain"


def allowed_numbers(model: Model, cards: list[dict]) -> list[float]:
    return [v for v, _ in allowed_entries(model, cards)]


def _decimals_tolerance(token: str) -> float:
    """Half a unit in the last digit the answer shows (so 1.9 matches 1.88, 3 matches 2.6)."""
    t = token.lstrip("+-").replace(",", "")
    mant = t.split("e")[0].split("E")[0]
    exp = int(t.lower().split("e")[1]) if "e" in t.lower() else 0
    dec = len(mant.split(".")[1]) if "." in mant else 0
    return 0.5 * 10 ** (exp - dec)


_UNIT_AFTER = re.compile(r"\s*(%|°|℃|[A-Za-z]|[가-힣]{0,1}(도|년|일|초|시간|분|배))")
_UNIT_TOKEN = re.compile(r"\s*(°\s?C|℃|도|퍼센트|%|m3/s|m3/d|L/s|m/s|m/d|m/yr|[kMG]?Pa|km|cm|mm|m(?![A-Za-z²³0-9/])|K(?![A-Za-z/])|"
                         r"years?|yr|days?|d(?![A-Za-z])|hours?|h(?![A-Za-z])|seconds?|s(?![A-Za-z])|년|일|시간|초)")
_UNIT_NAME = {"°C": "°C", "° C": "°C", "℃": "°C", "도": "°C", "퍼센트": "%", "year": "yr", "years": "yr", "day": "d",
              "days": "d", "hour": "h", "hours": "h", "second": "s", "seconds": "s", "년": "yr", "일": "d", "시간": "h",
              "초": "s"}
_RESULTS = {"temperature", "pressure", "velocity", "flow_rate"}  # never backed by a number seen in passing


def unit_dimension(text: str, end: int) -> str | None:
    m = _UNIT_TOKEN.match(text, end)
    if not m:
        return None
    u = m.group(1)
    return _DIM_OF_UNIT.get(_UNIT_NAME.get(u, u))


def check_answer(text: str, model: Model | None, cards: list[dict], seen: list[float] | None = None,
                 user_text: str = "") -> list[str]:
    """Numbers in the answer that match neither the card, the model inputs, the user's own words nor a number a tool
    reported. A number matches when it equals an allowed value rounded to the digits it shows; the sign is not
    compared, so 'drops 3.06 m' matches a change of -3.06 m. A number written with a unit must come from a source of
    that dimension: a temperature from a temperature on the card or in the inputs, not from a density. Numbers that
    tools reported in passing carry no dimension, so they back counts, lengths, times and percentages but never a
    temperature, pressure or flow."""
    allowed = allowed_entries(model, cards)
    allowed += [(float(x), "seen") for x in (seen or [])]
    allowed += [(float(m.group(0).replace(",", "")), None) for m in _NUM.finditer(user_text)
                if re.fullmatch(r"[-+]?[\d,]*\.?\d+(?:[eE][-+]?\d+)?", m.group(0))]
    allowed = [(a, d) for a, d in allowed if math.isfinite(a)]
    bad = []
    for m in _NUM.finditer(text):
        tok = m.group(0)
        s = tok.replace(",", "") if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+(\.\d+)?", tok) else tok.replace(",", ".")
        try:
            x = float(s)
        except ValueError:
            continue
        followed_by_unit = bool(_UNIT_AFTER.match(text, m.end()))
        if abs(x) <= 10 and float(x).is_integer() and not followed_by_unit:
            continue  # list numbers and counts, not quantities with a unit
        if 1900 <= x <= 2100 and float(x).is_integer() and not followed_by_unit:
            continue  # years
        dim = unit_dimension(text, m.end())
        tol = _decimals_tolerance(s)

        def fits(d):
            if d is None:
                return True                                   # the user's own numbers
            if d == "seen":
                return dim not in _RESULTS
            return dim is None or d == dim
        if not any(abs(abs(x) - abs(a)) <= max(tol, 1e-12 * abs(a)) and fits(d) for a, d in allowed):
            bad.append(tok)
    return bad


# ---------------------------------------------------------------- 3D view

VIEWER_JS = r"""
const D = JSON.parse(document.getElementById('d').textContent);
const b64 = (s, T) => { const r = atob(s), u = new Uint8Array(r.length); for (let i = 0; i < r.length; i++) u[i] = r.charCodeAt(i); return new T(u.buffer); };
const P = b64(D.p, Float32Array), I = b64(D.i, Uint32Array), V = b64(D.v, Float32Array);
const cv = document.getElementById('c'), gl = cv.getContext('webgl', {antialias: true});
gl.getExtension('OES_element_index_uint');
const VIR = [[68,1,84],[72,40,120],[62,74,137],[49,104,142],[38,130,142],[31,158,137],[53,183,121],[109,205,89],[180,222,44],[253,231,37]];
function col(x) { x = Math.min(1, Math.max(0, x)) * (VIR.length - 1); const i = Math.min(VIR.length - 2, Math.floor(x)), f = x - i;
  return VIR[i].map((c, k) => (c + f * (VIR[i + 1][k] - c)) / 255); }
const n = P.length / 3, C = new Float32Array(n * 3), N = new Float32Array(n * 3);
for (let k = 0; k < n; k++) { const c = col((V[k] - D.vmin) / (D.vmax - D.vmin || 1)); C.set(c, 3 * k); }
for (let t = 0; t < I.length; t += 3) { const a = I[t] * 3, b = I[t + 1] * 3, c = I[t + 2] * 3;
  const u = [P[b] - P[a], P[b + 1] - P[a + 1], P[b + 2] - P[a + 2]], w = [P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]];
  const nx = u[1] * w[2] - u[2] * w[1], ny = u[2] * w[0] - u[0] * w[2], nz = u[0] * w[1] - u[1] * w[0];
  for (const q of [a, b, c]) { N[q] += nx; N[q + 1] += ny; N[q + 2] += nz; } }
function sh(t, src) { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); return s; }
const pr = gl.createProgram();
gl.attachShader(pr, sh(gl.VERTEX_SHADER, 'attribute vec3 p,c,n;uniform mat4 m;varying vec3 vc;varying float l;void main(){gl_Position=m*vec4(p,1.);vec3 nn=normalize((m*vec4(n,0.)).xyz);l=.45+.55*abs(nn.z);vc=c;}'));
gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, 'precision mediump float;varying vec3 vc;varying float l;void main(){gl_FragColor=vec4(vc*l,1.);}'));
gl.linkProgram(pr); gl.useProgram(pr);
function buf(data, name, size) { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, name); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0); }
buf(P, 'p', 3); buf(C, 'c', 3); buf(N, 'n', 3);
const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, I, gl.STATIC_DRAW);
gl.enable(gl.DEPTH_TEST);
let yaw = -0.6, pitch = 0.5, zoom = 1, drag = null;
function mat() { const s = 1.6 * zoom / D.size, cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), a = cv.width / cv.height;
  const R = [cy, sy * sp, -sy * cp, 0, 0, cp, sp, 0, sy, -cy * sp, cy * cp, 0];
  const c = D.center, m = new Float32Array(16);
  for (let i = 0; i < 3; i++) { m[i] = R[i] * s / (i === 0 ? a : 1); m[4 + i] = R[4 + i] * s / (i === 0 ? a : 1); m[8 + i] = R[8 + i] * s / (i === 0 ? a : 1); }
  for (let i = 0; i < 3; i++) m[12 + i] = -(m[i] * c[0] + m[4 + i] * c[1] + m[8 + i] * c[2]);
  for (let i = 0; i < 4; i++) m[i * 4 + 2] *= 0.3; m[15] = 1; return m; }
function draw() { const r = devicePixelRatio || 1; cv.width = cv.clientWidth * r; cv.height = cv.clientHeight * r; gl.viewport(0, 0, cv.width, cv.height);
  gl.clearColor(1, 1, 1, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.uniformMatrix4fv(gl.getUniformLocation(pr, 'm'), false, mat()); gl.drawElements(gl.TRIANGLES, I.length, gl.UNSIGNED_INT, 0); }
cv.onpointerdown = e => { drag = [e.clientX, e.clientY, yaw, pitch]; cv.setPointerCapture(e.pointerId); };
cv.onpointermove = e => { if (!drag) return; yaw = drag[2] + (e.clientX - drag[0]) * 0.01; pitch = Math.max(-1.5, Math.min(1.5, drag[3] + (e.clientY - drag[1]) * 0.01)); draw(); };
cv.onpointerup = () => drag = null;
cv.onwheel = e => { e.preventDefault(); zoom *= Math.exp(-e.deltaY * 0.001); draw(); };
addEventListener('resize', draw);
const g = document.getElementById('bar'); g.style.background = 'linear-gradient(to right,' + VIR.map(c => `rgb(${c})`).join(',') + ')';
document.getElementById('lo').textContent = D.lo; document.getElementById('hi').textContent = D.hi;
draw();
"""


def viewer(results: Results, field: str, t: float, out: Path, max_triangles: int = 400_000) -> Path | None:
    """Offline interactive 3D view: one field on the model surface; axisymmetric models are revolved (270 degrees)."""
    import warnings
    warnings.filterwarnings("ignore", message="(?s).*extract_surface")
    try:
        m = results.mesh_at(t).copy()
        vals = results.field(m, field)
        if np.ndim(vals) == 2:
            vals = np.linalg.norm(vals, axis=1)
        _, du, f, o = DISPLAY.get(field, ("", "-", 1.0, 0.0))
        m.point_data["_v"] = np.asarray(vals, float) * f + o
        surf = m.extract_surface().triangulate() if np.ptp(m.points[:, 2]) > 0 else m.triangulate().extract_surface()
        if results.model is not None and results.model.geometry.kind in ("axisym_well", "axisym_source"):
            pts = surf.points.copy()
            surf.points = np.c_[pts[:, 0], np.zeros(len(pts)), pts[:, 1]]
            surf = surf.extrude_rotate(angle=270, resolution=54, rotation_axis=(0, 0, 1), capping=False).triangulate()
        surf = surf.extract_surface().triangulate()
        tri = surf.faces.reshape(-1, 4)[:, 1:]
        if len(tri) > max_triangles:
            return None
        P = surf.points.astype(np.float32)
        V = np.asarray(surf.point_data["_v"], np.float32)
        lo, hi = float(V.min()), float(V.max())
        data = {"p": base64.b64encode(P.tobytes()).decode(), "i": base64.b64encode(tri.astype(np.uint32).tobytes()).decode(),
                "v": base64.b64encode(V.tobytes()).decode(), "vmin": lo, "vmax": hi,
                "center": [float(x) for x in P.mean(0)], "size": float(np.ptp(P, 0).max()),
                "lo": f"{fmt(lo)} {du}", "hi": f"{fmt(hi)} {du}"}
        title = html.escape(f"{field} ({du}) at {time_text(t)}")
        out.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>3D view</title><style>body{{margin:0;font:14px -apple-system,sans-serif;background:#fff;color:#1d2a33}}
#c{{width:100vw;height:88vh;display:block;touch-action:none;cursor:grab}} .leg{{display:flex;align-items:center;gap:8px;padding:8px 16px}}
#bar{{flex:0 0 240px;height:12px;border:1px solid #ccd}} .t{{padding:8px 16px 0}}</style></head><body>
<div class="t">{title}. Drag to turn, scroll to zoom.</div><canvas id="c"></canvas>
<div class="leg"><span id="lo"></span><div id="bar"></div><span id="hi"></span></div>
<script id="d" type="application/json">{json.dumps(data)}</script><script>{VIEWER_JS}</script></body></html>""", encoding="utf-8")
        return out
    except Exception:  # the results page works without the 3D view
        return None


# ---------------------------------------------------------------- results page

def _img(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def results_page(model: Model, card: dict, figures: list[Path], out: Path, viewer: Path | None = None,
                 translation: list[str] | None = None) -> Path:
    e = html.escape
    rows = "".join(f"<tr><td>{e(r['label'])}</td><td>{e(r['location'])}</td><td>{e(r['time'])}</td>"
                   f"<td>{e(r['aggregation'])}</td><td class='num'>{e(r['value'])} {e(r['unit'])}</td></tr>"
                   for r in card["rows"])
    v = card["verification"]
    vrows = "".join(f"<li>{e(c['case'])}: {e(c['status'])}"
                    + (f", largest normalised error {fmt(100 * c['worst_normalised_error'], 2)} %" if "worst_normalised_error" in c else "")
                    + "</li>" for c in v["cases"])
    rc = "".join(f"<li>{e(k.replace('_', ' '))}: {e('; '.join(f'{a}: {b}' for a, b in val.items()) if isinstance(val, dict) else str(val))}</li>"
                 for k, val in card["run_checks"].items())
    figs = "".join(f"<figure><img src='{_img(p)}' alt='{e(p.stem)}'><figcaption>{e(p.stem.replace('_', ' '))}</figcaption></figure>"
                   for p in figures if Path(p).exists())
    tl = "".join(f"<li>{e(x)}</li>" for x in (translation or []))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(model.name)} results</title><style>
:root {{ --ink:#1d2a33; --muted:#5b6b75; --line:#d9e0e4; --bg:#fbfcfc; --accent:#2f6f8f; }}
@media (prefers-color-scheme: dark) {{ :root {{ --ink:#e6edf0; --muted:#a8b5bc; --line:#33424b; --bg:#141b1f; --accent:#7fb7d4; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }} h2 {{ font-size:1.1rem; margin:28px 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.meta {{ color:var(--muted); font-size:.9rem; }}
table {{ border-collapse:collapse; width:100%; font-size:.95rem; }} td,th {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
figure {{ margin:16px 0; }} img {{ max-width:100%; height:auto; border:1px solid var(--line); background:#fff; }}
figcaption {{ color:var(--muted); font-size:.85rem; }} a {{ color:var(--accent); }}
.note {{ color:var(--muted); font-size:.85rem; }}
</style></head><body><main>
<h1>{e(model.name.replace('_', ' '))}</h1>
<p class="meta">Run {e(card['run_id'])} · model {e(card['model_name'])} · {e(card['created'])} · computed with OpenGeoSys 6.5.8 through GeoAI-THM Studio</p>
<h2>Results</h2><table><tr><th>quantity</th><th>where</th><th>when</th><th>how</th><th>value</th></tr>{rows}</table>
<h2>Verification</h2><p>Configuration {e(str(v.get('configuration')))}{' (demonstration: checked for consistency, no exact solution)' if v.get('demonstration') else ''}.</p><ul>{vrows}</ul>
<p>Checks on this run:</p><ul>{rc}</ul>
<h2>Figures</h2>{figs}
{f"<p><a href='{e(viewer.name)}'>Open the 3D view</a> (works offline)</p>" if viewer else ''}
<h2>How the input was translated</h2><ul>{tl or '<li>no conversions</li>'}</ul>
<p class="note">GeoAI-THM Studio is free for noncommercial use. Site-specific, large or licensing studies: GeoAI Alignment, Inc.</p>
</main></body></html>"""
    out.write_text(page, encoding="utf-8")
    return out
