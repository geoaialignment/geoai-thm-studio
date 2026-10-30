"""Expose the tool registry as Agents SDK FunctionTools.

Schemas come from the same Pydantic input models the tools validate with
(strict mode). Visibility follows the session state; a call to a hidden tool
is answered with the state and the next step instead of ending the run.
"""
from __future__ import annotations

import json

from agents import FunctionTool, RunConfig, RunContextWrapper
from agents.strict_schema import ensure_strict_json_schema

from ..session import Session
from ..tools import TOOLS, call, not_available, visible_tools


def _doc(fn) -> str:
    return " ".join((fn.__doc__ or "").split())


def function_tools() -> list[FunctionTool]:
    tools = []
    for name, (model_cls, fn) in TOOLS.items():
        schema = ensure_strict_json_schema(model_cls.model_json_schema())

        async def invoke(ctx: RunContextWrapper[Session], args_json: str, _name=name) -> str:
            args = json.loads(args_json) if args_json else {}
            return json.dumps(call(ctx.context, _name, args), default=str, ensure_ascii=False)

        tools.append(FunctionTool(name=name, description=_doc(fn), params_json_schema=schema,
                                  on_invoke_tool=invoke, strict_json_schema=True,
                                  is_enabled=lambda ctx, agent, _n=name: _n in visible_tools(ctx.context)))
    return tools


def _format_tool_error(a) -> str | None:
    if a.kind == "tool_not_found":
        return not_available(a.run_context.context, a.tool_name)
    return None


def run_config() -> RunConfig:
    return RunConfig(tool_not_found_behavior="return_error_to_model", tool_error_formatter=_format_tool_error,
                     tracing_disabled=True)


def history_after_tripwire(e, history: list) -> list:
    """The conversation including the rejected run (its tool calls and answer), so a retry continues from there."""
    rd = getattr(e, "run_data", None)
    if rd is None:
        return list(history)
    start = rd.input if isinstance(rd.input, list) else [{"role": "user", "content": rd.input}]
    return list(start) + [item.to_input_item() for item in rd.new_items]
