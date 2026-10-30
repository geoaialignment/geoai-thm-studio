"""Collect every number the technical notes and the preprint quote into docs/numbers.json, from the result files."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from thmstudio import configs  # noqa: E402
from thmstudio.tools import TOOLS  # noqa: E402

N = {}
rec = json.loads((ROOT / "src/thmstudio/verification_record.json").read_text())
worst = {r["id"]: max(k["max_norm_error"] for k in r["checks"]) for r in rec}
N["cases"] = len(rec)
N["cases_passed"] = sum(r["passed"] for r in rec)
N["cases_within_1pct"] = sum(w <= 0.01 for w in worst.values())
N["cases_max_pct"] = round(100 * max(worst.values()), 2)
N["case_worst_pct"] = {k: round(100 * v, 3) for k, v in worst.items()}
N["configurations"] = len(configs.CONFIGURATIONS)
N["package_version"] = rec[0].get("package_version")
N["ogs_version"] = rec[0].get("ogs_version")
N["tools"] = len(TOOLS)
hv = ROOT / "results/verification_halving.json"
if hv.exists():
    H = json.loads(hv.read_text())
    tr = [r["ratio"] for r in H["cases"] if not r["steady"]]
    st = [r for r in H["cases"] if r["steady"]]
    N["halving_n"], N["halving_min"], N["halving_max"] = len(tr), round(min(tr), 2), round(max(tr), 2)
    import statistics
    N["halving_median"] = round(statistics.median(tr), 2)
    st_txt = "; in the steady case refined with them, " + st[0]["id"] + f", it fell to {st[0]['ratio']:.2f}" if st else ""
    N["halving_sentence"] = (f"Halving the element size and the time step together in {len(tr)} transient cases reduced their "
                             f"largest errors to {N['halving_min']:.2f}–{N['halving_max']:.2f} of their values (median "
                             f"{N['halving_median']:.2f}), as first-order time stepping leads one to expect{st_txt}; the "
                             f"refined run of the point-source case did not finish within the run-time limit.")
    st_ko = f" 함께 세분한 정상 사례 {st[0]['id']}에서는 {st[0]['ratio']:.2f}배로 줄었다." if st else ""
    N["halving_sentence_ko"] = (f"요소 크기와 시간 간격을 함께 절반으로 줄이자 비정상 사례 {len(tr)}개의 최대 오차가 원래의 "
                                f"{N['halving_min']:.2f}–{N['halving_max']:.2f}배(중앙값 {N['halving_median']:.2f}배)로 "
                                f"줄었으며, 이는 1차 시간 적분에서 기대되는 결과이다.{st_ko} 점 열원 사례의 세분 계산은 "
                                f"실행 시간 상한 안에 끝나지 않았다.")
l6 = json.loads((ROOT / "results/l6_rescored.json").read_text())
N["l6_n"] = len(l6)
N["l6_passed"] = sum(r["passed"] for r in l6)
N["l6_failed"] = [r["id"] for r in l6 if not r["passed"]]
N["l6_calls"] = sum(r["calls"] or 0 for r in l6)
N["l6_errors"] = sum(r["errors"] or 0 for r in l6)
N["l6_runs_with_errors"] = sum(1 for r in l6 if r["errors"])

led = json.loads((ROOT / "tests/final_api/ledger.json").read_text())
N["api_cost_usd"] = round(sum(r["cost_usd"] or 0 for r in led), 2)
N["api_metered_usd"] = round(sum(r["cost_usd"] or 0 for r in led if r.get("attempt") != "crashed"), 2)
N["api_booked_crashed_usd"] = round(sum(r["cost_usd"] or 0 for r in led if r.get("attempt") == "crashed"), 2)
first = {}
for r in led:  # the first completed run of each model and scenario
    if r.get("attempt") == "crashed" or r.get("calls") == 0 and r["id"] != "s02_out_of_scope":
        continue
    first.setdefault((r["model"], r["id"]), r)
N["api_runs"] = len(first)
N["api_scenarios"] = len({k[1] for k in first})
N["api_passed"] = sum(1 for r in first.values() if r["passed"])
N["api_card_only"] = sum(1 for r in first.values() if r["checks"].get("numbers_from_card", True) and r["passed"])
N["api_loop_failures"] = sum(1 for r in led if "Event loop is closed" in (r.get("note") or ""))
s11 = [r for r in led if r["id"] == "s11_thermal_pressurisation"]
N["s11_answers_MPa"] = {"luna_no_rule": -0.507, "terra_no_rule": 0.635, "luna_rule_half": 0.998, "terra_rule_half": 0.887,
                        "terra_rule_quarter": 0.971}
for k, v in N["s11_answers_MPa"].items():  # each value must appear in the recorded answer text
    assert any(f"{abs(v):.3f}" in r["final"] for r in s11), (k, v)
N["s11_calls"] = [r["calls"] for r in s11]
sweep = json.loads((ROOT / "results/point_source_sweep.json").read_text())
N["s11_exact_MPa"] = round(sweep["exact_MPa"], 3)
N["s11_ell_m"] = round(sweep["ell_m"], 3)
sys.path.insert(0, str(ROOT / "scripts"))
from sweep_point_source import params  # noqa: E402
from thmstudio import analytic as an  # noqa: E402
src = an.PointHeatSource(**params())
N["s11_exact_T_K"] = round(float(src.temperature(0.5, 50000.0)[0]) - params()["T0"], 2)
N["s11_c_over_kappa"] = round(src.c / src.kappa, 2)
N["terra_half_size_diff_MPa"] = 0.257  # runs/final_api/gpt-6.1-terra/s11_..._before_source_check/*/cards.json
c0 = json.loads(next((ROOT / "runs/final_api/gpt-6.1-terra/s11_thermal_pressurisation_before_source_check").glob("*/cards.json")).read_text())
assert any(r["value"] == "0.257" for card in c0 for r in card["rows"])
N["sweep"] = sweep["rows"]
N["luna_steps_MPa"] = round(next(r["pressure_MPa"] for r in sweep["rows"] if r.get("study")), 3)
audit = json.loads((ROOT / "results/api_mesh_audit.json").read_text())
other = [a for a in audit if not a["scenario"].startswith("s11")]
N["audit_other_n"] = len(other)
N["audit_other_max_pct"] = round(max(a["diff_pct"] for a in other), 1)
N["audit_other_within_02"] = sum(a["diff_pct"] <= 0.2 for a in other)
N["audit_other_second_pct"] = round(sorted(a["diff_pct"] for a in other)[-2], 1)
N["audit"] = audit
from thmstudio.schema import Model  # noqa: E402
changed, runs = [], 0
for (m, sid), r in first.items():
    if sid == "s02_out_of_scope":
        continue
    folder = sid + "_before_source_check" if sid.startswith("s11") else sid  # first-pass s11 runs were kept apart
    projs = [p for p in (ROOT / "runs/final_api" / m / folder).glob("*") if (p / "model.json").exists()]
    if not projs:
        continue
    P = projs[0]
    log = [json.loads(x) for x in (P / "audit.log").read_text().splitlines()]
    ex = next(json.loads(a["args"])["example_id"] for a in log if a["tool"] == "start_from_example" and a["ok"])
    mm = Model.model_validate_json((P / "model.json").read_text()).mesh.model_dump()
    em = Model.model_validate(json.loads((ROOT / f"src/thmstudio/examples/{ex}.json").read_text())["model"]).mesh.model_dump()
    mm.pop("element", None); em.pop("element", None)
    runs += 1
    if mm != em:
        changed.append(f"{m} {sid}")
N["mesh_runs"] = runs
N["mesh_changed"] = len(changed)
N["mesh_changed_runs"] = changed
import subprocess
out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"], cwd=ROOT, capture_output=True, text=True).stdout
N["tests"] = int([l for l in out.splitlines() if "tests collected" in l or "test collected" in l][0].split()[0])
(ROOT / "docs/numbers.json").write_text(json.dumps(N, indent=1, ensure_ascii=False))
print(json.dumps({k: v for k, v in N.items() if k not in ("sweep", "audit", "case_worst_pct")}, indent=1))
