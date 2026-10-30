"""L4: the tool registry through the Agents SDK with a scripted fake model (no API, no network)."""
import asyncio
import json
import socket

import pytest
from agents import Agent, Runner, set_tracing_disabled
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from thmstudio.agent.sdk import function_tools, run_config
from thmstudio.session import Session

set_tracing_disabled(True)


class Scripted(Model):
    def __init__(self, script):
        self.script, self.seen = list(script), []

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, **kw):
        self.seen.append(sorted(t.name for t in tools))
        name, args = self.script.pop(0)
        n = len(self.seen)
        if name is None:
            out = [ResponseOutputMessage(id="m", role="assistant", status="completed", type="message",
                                         content=[ResponseOutputText(text=args, type="output_text", annotations=[])])]
        else:
            out = [ResponseFunctionToolCall(id=f"fc{n}", call_id=f"c{n}", name=name, arguments=json.dumps(args),
                                            type="function_call", status="completed")]
        return ModelResponse(output=out, usage=Usage(), response_id=None)

    async def stream_response(self, *a, **k):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(self, addr):
        raise RuntimeError(f"network blocked: {addr}")
    monkeypatch.setattr(socket.socket, "connect", blocked)


def test_all_schemas_are_strict():
    tools = function_tools()
    assert len(tools) >= 18
    for t in tools:
        assert t.strict_json_schema and t.params_json_schema["additionalProperties"] is False


def test_t_flow_through_sdk_with_recovery(tmp_path):
    script = [
        ("start_from_example", {"example_id": "surface_heating", "changes": [{"name": "duration", "value": "2 yr"}],
                                "project_name": None}),
        ("run", {}),                       # hidden in DRAFT: must not end the run
        ("build_mesh", {}),
        ("check_model", {}),
        ("run", {}),
        ("run_status", {}),
        ("show_results", {"field": "temperature", "kind": "profile", "time": None, "probe": "depth_profile",
                          "point": None, "line": None}),
        (None, "done"),
    ]
    model = Scripted(script)
    s = Session(root=tmp_path)
    agent = Agent(name="thm", instructions="test", tools=function_tools(), model=model)
    r = asyncio.run(Runner.run(agent, "heat the rock surface", context=s, max_turns=40, run_config=run_config()))
    assert r.final_output == "done"
    assert s.state == "COMPUTED"
    outs = [json.loads(i["output"]) if i["output"].startswith("{") else i["output"]
            for i in r.to_input_list() if i.get("type") == "function_call_output"]
    hidden = outs[1]
    text = hidden if isinstance(hidden, str) else hidden.get("error", "")
    assert "not available" in text and "build_mesh" in text
    assert outs[-1]["ok"] and outs[-1]["picture"].endswith(".png")
    assert all(len(seen) <= 6 for seen in model.seen)


def test_dynamic_instructions_and_guardrail(tmp_path):
    from thmstudio.agent.build import build_agent
    script = [
        ("start_from_example", {"example_id": "surface_heating", "changes": [{"name": "duration", "value": "2 yr"}],
                                "project_name": None}),
        ("build_mesh", {}), ("check_model", {}), ("run", {}), ("run_status", {}),
        ("answer_card", {"items": [{"label": "temperature at 5 m depth", "kind": "value", "field": "temperature",
                                    "component": None, "probe": "at_5m", "point": None, "time": None, "comparison": None}]}),
        (None, "The rock at 5 m depth warms to 123.4 °C."),   # not on the card: must trip
    ]
    s = Session(root=tmp_path)
    agent = build_agent(Scripted(script))
    from agents.exceptions import OutputGuardrailTripwireTriggered
    with pytest.raises(OutputGuardrailTripwireTriggered) as e:
        asyncio.run(Runner.run(agent, "warm the surface", context=s, max_turns=40, run_config=run_config()))
    assert "123.4" in e.value.guardrail_result.output.output_info["unsupported_numbers"]
    from thmstudio.agent.sdk import history_after_tripwire
    hist = history_after_tripwire(e.value, [])
    assert hist[0]["content"] == "warm the surface" and len(hist) > 2  # the rejected run is kept for the retry
    card_value = s.cards[-1]["rows"][0]["value"]
    s2 = Session(root=tmp_path / "b")
    script[-1] = (None, f"At 5 m depth the rock reaches {card_value} °C after 2 years (surface at 25 °C).")
    r = asyncio.run(Runner.run(build_agent(Scripted(script)), "warm the surface", context=s2, max_turns=40,
                               run_config=run_config()))
    assert card_value in r.final_output
    from thmstudio.agent.build import instructions
    from agents import RunContextWrapper
    text = instructions(RunContextWrapper(s2), None)
    assert "State: REPORTED" in text and "answer_card" in text
