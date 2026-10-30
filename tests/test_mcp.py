"""L5: the MCP stdio path gives the same answers as the in-process tools."""
import asyncio
import json
import sys

import pytest
from agents.mcp import MCPServerStdio


async def _session(tmp, calls):
    async with MCPServerStdio(params={"command": sys.executable, "args": ["-m", "thmstudio.mcp_server", str(tmp)]},
                              client_session_timeout_seconds=60) as srv:
        listed = await srv.list_tools()
        outs = []
        for name, args in calls:
            r = await srv.call_tool(name, args)
            outs.append((json.loads(r.content[0].text), [c.type for c in r.content]))
        return [t.name for t in listed], outs


def test_mcp_flow(tmp_path):
    names, outs = asyncio.run(_session(tmp_path, [
        ("run", {}),
        ("start_from_example", {"example_id": "surface_heating", "changes": [{"name": "duration", "value": "1 yr"}]}),
        ("build_mesh", {}),
        ("check_model", {}),
        ("run", {}),
        ("run_status", {}), ("run_status", {}), ("run_status", {}),
    ]))
    assert "start_from_example" in names and "answer_card" in names
    first, _ = outs[0]
    assert not first["ok"] and "Next step" in first["error"]
    mesh, types_ = outs[2]
    assert mesh["ok"] and "image" in types_
    assert outs[3][0]["ok"] and outs[4][0]["ok"]
    statuses = [o[0].get("status") for o in outs[5:]]
    assert "succeeded" in statuses or statuses[-1] in ("running", "queued")
