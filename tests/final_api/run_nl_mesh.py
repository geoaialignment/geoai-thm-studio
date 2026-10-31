"""One recorded conversation for the v0.1.1 technical note: a mesh built and refined from plain-language requests.

Model gpt-6.1-terra through the OpenAI API (author's approval of 2026-10-31, budget below USD 0.10). The key is read
from the environment only. Every turn, its tool calls and its cost are written to nl_mesh_ledger.json; the session
folder (model tree, mesh pictures, audit log) is kept under scratch/nl_mesh/.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
MODEL = "gpt-6.1-terra"
PRICE = (1.00, 5.00)            # USD per 1M input / output tokens (OpenAI pricing page, checked 2026-10-30)
CAP = 0.10
LEDGER = ROOT / "tests" / "final_api" / "nl_mesh_ledger.json"
OUT = ROOT / "scratch" / "nl_mesh"
TURNS = [
    "처분공 하나를 모델링하려고 해. 반지름 0.5 m, 길이 4.8 m인 처분용기를 두께 0.35 m 벤토나이트 완충재가 감싸고, "
    "그 바깥은 포화된 화강암이야. 처분용기 발열은 1700 W. 물성은 예제 기본값을 써도 돼. 계산은 아직 하지 말고 "
    "격자까지 만들어서 보여 줘.",
    "처분용기 표면과 완충재-암반 경계 쪽 요소를 더 촘촘하게 해 줘. 경계에서 요소 크기가 2 cm 정도면 좋겠어. "
    "바뀐 격자를 다시 보여 주고, 요소 수가 얼마나 늘었는지 알려 줘.",
]


async def main() -> None:
    from agents import RunHooks, Runner, set_tracing_disabled
    from agents.exceptions import OutputGuardrailTripwireTriggered

    from thmstudio.agent.build import build_agent
    from thmstudio.agent.sdk import history_after_tripwire, run_config
    from thmstudio.session import Session

    meter = {"in": 0, "out": 0}

    def cost() -> float:
        return meter["in"] / 1e6 * PRICE[0] + meter["out"] / 1e6 * PRICE[1]

    class Hooks(RunHooks):
        async def on_llm_end(self, context, agent, response):
            meter["in"] += response.usage.input_tokens
            meter["out"] += response.usage.output_tokens
            if cost() > CAP:
                raise RuntimeError(f"budget cap USD {CAP} reached")

        async def on_tool_start(self, context, agent, tool):
            calls.append(tool.name)

    set_tracing_disabled(True)
    OUT.mkdir(parents=True, exist_ok=True)
    s = Session(root=OUT)
    agent = build_agent(MODEL)
    history: list = []
    rows = []
    for text in TURNS:
        calls: list[str] = []
        history.append({"role": "user", "content": text})
        s.user_texts.append(text)
        t0 = time.time()
        final, note = "", ""
        for attempt in range(2):
            try:
                r = await Runner.run(agent, history, context=s, max_turns=60, run_config=run_config(), hooks=Hooks())
                history = r.to_input_list()
                final = str(r.final_output)
                break
            except OutputGuardrailTripwireTriggered as e:
                bad = e.guardrail_result.output.output_info.get("unsupported_numbers", [])
                note += f"guardrail tripped on {bad}; "
                history = history_after_tripwire(e, history) + [{"role": "user", "content":
                          f"Your answer quoted numbers not on the answer card or in my inputs: {', '.join(bad)}. "
                          "Rewrite it using only card numbers."}]
            except Exception as e:  # budget cap or API failure: record and stop
                note += f"error {type(e).__name__}: {str(e)[:200]}; "
                break
        rows.append({"request": text, "answer": final, "tool_calls": calls, "note": note,
                     "seconds": round(time.time() - t0, 1), "cost_usd_so_far": round(cost(), 4)})
        print(json.dumps(rows[-1], ensure_ascii=False)[:1500], flush=True)
        if note.startswith("error"):
            break
    LEDGER.write_text(json.dumps({"model": MODEL, "date": time.strftime("%Y-%m-%d %H:%M"),
                                  "input_tokens": meter["in"], "output_tokens": meter["out"],
                                  "cost_usd": round(cost(), 4), "session": str(s.dir.relative_to(ROOT)) if s.dir else None,
                                  "turns": rows}, indent=1, ensure_ascii=False))
    print(f"total cost USD {cost():.4f}")


if __name__ == "__main__":
    asyncio.run(main())
