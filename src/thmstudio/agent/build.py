"""The agent: dynamic instructions, the tools, and the output guardrail on numbers."""
from __future__ import annotations

from pathlib import Path

from agents import Agent, GuardrailFunctionOutput, ModelSettings, RunContextWrapper, output_guardrail

from ..check import tree_summary
from ..report import check_answer
from ..session import Session
from ..tools import next_step, visible_tools
from .sdk import function_tools

HERE = Path(__file__).parent
DEFAULT_MODEL = "gpt-6.1-terra"
LIGHT_MODEL = "gpt-6-luna"


def _read(*parts) -> str:
    return (HERE.joinpath(*parts)).read_text().strip()


def instructions(ctx: RunContextWrapper[Session], agent: Agent) -> str:
    s = ctx.context
    parts = [_read("instructions", "system_prompt.md"), _read("instructions", "rules.md"),
             _read("instructions", "policies.md")]
    if s.state == "DRAFT" and s.focus != "check":
        parts.append(_read("skills", f"{s.focus}.md"))
    elif s.state in ("COMPUTED", "REPORTED"):
        parts.append(_read("skills", "results.md"))
    parts.append(f"# Now\nState: {s.state}" + (f", step {s.focus}" if s.state == "DRAFT" else "")
                 + f".\nModel: {tree_summary(s.model, s.mesh['summary'] if s.mesh else None)}"
                 + f"\nNext step: {next_step(s)}.\nTools available now: {', '.join(visible_tools(s))}.")
    return "\n\n".join(parts)


@output_guardrail
async def numbers_from_card(ctx: RunContextWrapper[Session], agent: Agent, output) -> GuardrailFunctionOutput:
    s = ctx.context
    text = output if isinstance(output, str) else str(output)
    bad = check_answer(text, s.model, s.cards, list(s.seen_numbers), " ".join(s.user_texts))
    return GuardrailFunctionOutput(output_info={"unsupported_numbers": bad}, tripwire_triggered=bool(bad))


def build_agent(model: str | object = DEFAULT_MODEL) -> Agent[Session]:
    return Agent(name="GeoAI-THM Studio", instructions=instructions, tools=function_tools(), model=model,
                 output_guardrails=[numbers_from_card], model_settings=ModelSettings(parallel_tool_calls=False))
