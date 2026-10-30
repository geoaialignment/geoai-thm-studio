"""S7 final check: fixed scenarios with the real OpenAI models, hard budget cap (USD 10 in total).

Prices (USD per 1M tokens, OpenAI pricing page, checked 2026-10-30): gpt-6-luna 0.10 in / 0.50 out,
gpt-6.1-terra 1.00 in / 5.00 out. All input is priced as uncached, so the estimate is an upper bound.
The key is read from the environment only. Results are written as they are, failures included.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "l6"))

PRICE = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-terra": (1.00, 5.00)}
BUDGET = 10.0
STOP_AT = 9.0                 # leave a margin under the cap
SCENARIOS = ["s01_surface_heating_ko", "s02_out_of_scope", "s04_pumping_well", "s06_heat_plume", "s07_tracer",
             "s09_consolidation", "s10_thermal_stress", "s11_thermal_pressurisation"]
LEDGER = ROOT / "tests" / "final_api" / "ledger.json"
LOOP = asyncio.new_event_loop()  # one loop for all scenarios: the model client is bound to it
LAST_COST = {"cost": 0.0}   # the running cost of the current scenario, kept if it crashes


def spent() -> float:
    return sum(r["cost_usd"] for r in json.loads(LEDGER.read_text())) if LEDGER.exists() else 0.0


class _Meter:
    """Counts every model response, including those of runs that end in an exception."""

    def __init__(self, model: str):
        from agents import RunHooks

        meter = self

        class Hooks(RunHooks):
            async def on_llm_end(self, context, agent, response):
                meter.inp += response.usage.input_tokens
                meter.out += response.usage.output_tokens
                LAST_COST["cost"] = meter.cost()
                if spent() + meter.cost() > BUDGET - 0.25:
                    raise RuntimeError("budget cap reached inside a run")

        self.inp = self.out = 0
        self.price = PRICE[model]
        self.hooks = Hooks()

    def cost(self) -> float:
        return self.inp / 1e6 * self.price[0] + self.out / 1e6 * self.price[1]


async def one(model: str, sc: dict, out: Path) -> dict:
    from agents import Runner, set_tracing_disabled
    from agents.exceptions import MaxTurnsExceeded, OutputGuardrailTripwireTriggered
    from thmstudio.agent.build import build_agent
    from thmstudio.agent.sdk import history_after_tripwire, run_config
    from thmstudio.session import Session
    set_tracing_disabled(True)
    s = Session(root=out)
    s.user_texts.append(sc["request"])
    agent = build_agent(model)
    history = [{"role": "user", "content": sc["request"]}]
    meter = _Meter(model)
    LAST_COST["cost"] = 0.0
    final, note = "", ""
    for attempt in range(2):
        try:
            r = await Runner.run(agent, history, context=s, max_turns=80, run_config=run_config(), hooks=meter.hooks)
            final = str(r.final_output)
            break
        except OutputGuardrailTripwireTriggered as e:
            bad = e.guardrail_result.output.output_info.get("unsupported_numbers", [])
            note += f"guardrail tripped on {bad}; "
            history = history_after_tripwire(e, history) + [
                {"role": "user", "content": f"Your answer quoted numbers not on the answer card or in my inputs: "
                                            f"{', '.join(bad)}. Rewrite it using only card numbers."}]
        except MaxTurnsExceeded:
            note += "max turns reached; "
            break
        except Exception as e:  # API or tool failure: record it and its cost, do not retry
            note += f"error {type(e).__name__}: {str(e)[:200]}; "
            break
    cost = meter.cost()
    return {"final": final, "note": note, "input_tokens": meter.inp, "output_tokens": meter.out, "cost_usd": cost}


def main(model: str = "gpt-6-luna", ids: list[str] | None = None):
    from run_l6 import judge
    scenarios = {s["id"]: s for s in json.loads((ROOT / "tests" / "l6" / "scenarios.json").read_text())}
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    for sid in ids or SCENARIOS:
        if spent() >= STOP_AT:
            print(f"budget stop: {spent():.2f} USD spent")
            break
        sc = scenarios[sid]
        out = ROOT / "scratch" / "final_api" / model / sid
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            res = LOOP.run_until_complete(one(model, sc, out))
        except Exception as e:  # never lose the cost of a scenario that crashed
            res = {"final": "", "note": f"runner crash {type(e).__name__}: {str(e)[:200]}", "input_tokens": 0,
                   "output_tokens": 0, "cost_usd": LAST_COST.get("cost", 0.0)}
        audits = []
        for f in out.glob("*/audit.log"):
            audits += [json.loads(l) for l in f.read_text().splitlines()]
        j = judge(sc, {"final": res["final"], "audit": audits, "projects": [str(p) for p in out.iterdir() if p.is_dir()],
                       "seconds": round(time.time() - t0, 1), "turns": None, "cost_usd": res["cost_usd"]})
        row = {"model": model, **j, **{k: res[k] for k in ("note", "input_tokens", "output_tokens", "cost_usd")},
               "final": res["final"][:3000], "date": time.strftime("%Y-%m-%d %H:%M")}
        ledger.append(row)
        LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=False))
        print(json.dumps({k: row[k] for k in ("model", "id", "passed", "checks", "cost_usd", "seconds", "note")},
                         ensure_ascii=False), f"total {spent():.3f} USD", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gpt-6-luna", sys.argv[2:] or None)
