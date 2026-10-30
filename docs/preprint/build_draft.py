"""Assemble docs/preprint/draft.md from sections/*.md, filling {{...}} from docs/numbers.json and the result files."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
N = json.loads((ROOT / "docs/numbers.json").read_text())
DOI = (HERE / "DOI").read_text().strip() if (HERE / "DOI").exists() else "{{doi}}"

PHYS = {"H-2D": "groundwater flow, 2D", "H-AX-well": "radial flow to a well", "H-3D": "groundwater flow, 3D box",
        "T-2D": "heat conduction, 2D", "T-3D": "heat conduction, 3D box", "TH-2D": "heat carried by groundwater flow",
        "HC-2D": "solute transport with sorption and decay", "HC-2D-density": "density-driven solute transport",
        "HM-2D": "consolidation (plane strain)", "TM-2D": "thermal stress (plane strain)",
        "THM-AX": "point heat source in saturated rock", "THM-AX-repository": "heated canister in a buffer (demonstration)"}
REF = {"V1a": "layers in series", "V1b": "Theis (1935)", "V1c": "hydrostatics", "V1c-flow": "Darcy, layers",
       "V2a": "erfc solution", "V2a-tri": "erfc, triangles", "V2a-official": "official input", "V2b": "uniform source",
       "V2b-power": "source as power", "V2d": "radial inclusion", "V2c": "erfc in 3D", "V2c-steady": "layers in series",
       "V3": "advection–conduction", "V3-water": "same, porosity 1", "V3-official": "official input",
       "V6a": "Ogata & Banks (1961)", "V6b": "van Genuchten & Alves (1982)", "V6b-official": "official input",
       "E2": "official Elder output", "V4": "Terzaghi", "V4b": "Biot coefficient 0.6", "V7a": "free expansion",
       "V7b": "constrained block", "V7c": "confined column", "V5": "Booker & Savvidou (1985)",
       "E1": "energy balance, convergence", "E1a": "homogeneous limit"}


def pct(x):
    return "< 0.0001 %" if x < 1e-4 else f"{x:.2g} %"


def table1():
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from thmstudio import configs
    cases = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in (ROOT / "src/thmstudio/cases").glob("*.json")}
    lines = ["| Configuration | Physics | Cases (reference) | Largest error |",
             "|--------------|----------------|------------------------------------------|--------|"]
    for cfg in configs.CONFIGURATIONS:
        ids = list(cfg.cases) + [i for i, c in cases.items() if c.get("kind") == "official" and c["configuration"] == cfg.id]
        w = max(N["case_worst_pct"][i] for i in ids)
        lines.append(f"| {cfg.id} | {PHYS[cfg.id]} | " + "; ".join(f"{i} ({REF[i]})" for i in ids) + f" | {pct(w)} |")
    return "\n".join(lines)


PHYS_KO = {"H-2D": "지하수 흐름, 2차원", "H-AX-well": "우물로 향하는 방사상 흐름", "H-3D": "지하수 흐름, 3차원 상자",
           "T-2D": "열전도, 2차원", "T-3D": "열전도, 3차원 상자", "TH-2D": "지하수 흐름에 의한 열 이동",
           "HC-2D": "용질 이동(흡착, 붕괴 포함)", "HC-2D-density": "밀도 차에 의한 용질 이동",
           "HM-2D": "압밀(평면 변형)", "TM-2D": "열응력(평면 변형)", "THM-AX": "포화 암반 속 점 열원",
           "THM-AX-repository": "완충재 속 발열 용기(시연)"}
REF_KO = {"V1a": "직렬 층", "V1b": "Theis (1935)", "V1c": "정수압", "V1c-flow": "Darcy, 층", "V2a": "erfc 해",
          "V2a-tri": "erfc, 삼각형", "V2a-official": "공식 입력", "V2b": "균일 열원", "V2b-power": "전체 발열률로 준 열원",
          "V2d": "원형 포함체", "V2c": "3차원 erfc", "V2c-steady": "직렬 층", "V3": "이류–전도",
          "V3-water": "공극률 1", "V3-official": "공식 입력", "V6a": "Ogata & Banks (1961)",
          "V6b": "van Genuchten & Alves (1982)", "V6b-official": "공식 입력", "E2": "공식 Elder 출력",
          "V4": "Terzaghi", "V4b": "Biot 계수 0.6", "V7a": "자유 팽창", "V7b": "구속 블록", "V7c": "측면 구속 기둥",
          "V5": "Booker & Savvidou (1985)", "E1": "에너지 수지, 수렴", "E1a": "균질 극한"}


def table1_ko():
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from thmstudio import configs
    cases = {json.loads(p.read_text())["id"]: json.loads(p.read_text()) for p in (ROOT / "src/thmstudio/cases").glob("*.json")}
    lines = ["| 구성 | 물리 | 검증 사례(기준) | 최대 오차 |",
             "|--------------|----------------|------------------------------------------|--------|"]
    for cfg in configs.CONFIGURATIONS:
        ids = list(cfg.cases) + [i for i, c in cases.items() if c.get("kind") == "official" and c["configuration"] == cfg.id]
        w = max(N["case_worst_pct"][i] for i in ids)
        lines.append(f"| {cfg.id} | {PHYS_KO[cfg.id]} | " + "; ".join(f"{i} ({REF_KO[i]})" for i in ids) + f" | {pct(w)} |")
    return "\n".join(lines)


SCEN = {"s01_surface_heating_ko": "surface warmed 10 K for 10 years: rise at 5 m (Korean)",
        "s02_out_of_scope": "reactive uranium transport, fractured granite (refuse)",
        "s04_pumping_well": "well pumping 500 m³/d: drawdown at 50 m after 1 day",
        "s06_heat_plume": "water 10 K warmer entering a sand aquifer: spread after 100 days (Korean)",
        "s07_tracer": "tracer at 0.0864 m/d: concentration 5 m downstream after 10 days",
        "s09_consolidation": "10 m clay under 50 kPa: settlement after 1 year",
        "s10_thermal_stress": "confined granite heated to 60 °C: thermal stress",
        "s11_thermal_pressurisation": "300 W point source: pore-pressure rise and the water's share (Korean)"}


def table2():
    led = json.loads((ROOT / "tests/final_api/ledger.json").read_text())
    first = {}
    for r in led:
        if r.get("attempt") == "crashed" or (r.get("calls") == 0 and r["id"] != "s02_out_of_scope"):
            continue
        first.setdefault((r["model"], r["id"]), r)
    aud = {}
    for a in N["audit"]:  # first-pass s11 runs are stored under s11_..._before_source_check
        sc = a["scenario"].replace("_before_source_check", "")
        if sc in SCEN and (not sc.startswith("s11") or a["scenario"].endswith("_before_source_check")):
            aud.setdefault((a["model"], sc), []).append(a["diff_pct"])
    def f(x):
        return "no card" if x is None else (f"{x:.2g} %" if x < 10 else f"{x:.0f} %")
    lines = ["| Scenario | Request | Calls, luna | Audit, luna | Calls, terra | Audit, terra |",
             "|------|------------------------------------------|--------|--------|--------|--------|"]
    for sid, txt in SCEN.items():
        cells = []
        for m in ("gpt-6-luna", "gpt-6.1-terra"):
            r = first[(m, sid)]
            d = aud.get((m, sid))
            cells += [str(r["calls"]), "no card" if sid == "s02_out_of_scope" else f(max(d) if d else None)]
        lines.append(f"| {sid.split('_')[0]} | {txt} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def table3():
    ex = json.loads((ROOT / "results/point_source_sweep.json").read_text())["exact_MPa"]  # unrounded
    rows = [("gpt-6-luna, no rule", "0.2", "far field 1 m", -0.507), ("gpt-6.1-terra, no rule", "0.1", "as example", 0.635),
            ("gpt-6-luna, rule ℓ/2", "0.05", "100 × 100 elements, steps ≤ 5,000 s", 0.998),
            ("gpt-6.1-terra, rule ℓ/2", "0.05", "as example", 0.887),
            ("gpt-6.1-terra, rule ℓ/4", "0.0145", "far field 0.2 m", 0.971)]
    lines = ["| Run | h (m) | Other settings | Pressure rise (MPa) | Error |",
             "|----------------------|-------|------------------------|--------|--------|"]
    for name, h, other, p in rows:
        lines.append(f"| {name} | {h} | {other} | {p:.3f} | {100 * (p - ex) / ex:+.1f} % |")
    for r in sorted(N["sweep"], key=lambda r: -r["h"]):
        other = "first and largest step, output time as gpt-6-luna" if r.get("study") else "as example"
        lines.append(f"| sweep, h/ℓ = {r['h_over_ell']:.2f} | {r['h']:g} | {other} | {r['pressure_MPa']:.3f} | "
                     f"{r['error_pct']:+.1f} % |")
    return "\n".join(lines)


def fill(text):
    text = text.replace("{{TABLE1}}", table1()).replace("{{TABLE2}}", table2()).replace("{{TABLE3}}", table3()).replace("{{doi}}", DOI)
    for k, v in N.items():
        if isinstance(v, (int, float, str)):
            text = text.replace("{{" + k + "}}", str(v))
    return text


if __name__ == "__main__":
  parts = [fill((HERE / "sections" / f).read_text()) for f in
         ("0_front.md", "1_intro.md", "2_methods.md", "3_results.md", "4_discussion.md", "9_back.md", "9_refs.md")]
  out = "\n\n".join(parts)
  left = sorted(set(re.findall(r"\{\{[^}]+\}\}", out)))
  (HERE / "draft.md").write_text(out)
  print("placeholders left:", left)
