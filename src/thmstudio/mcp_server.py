"""MCP stdio adapter: the same tools and state machine for external clients (e.g. Claude Desktop).

All tools are listed (strong clients can choose); a call that does not fit the state returns the
state and the next step. Long work returns at once: poll run_status, call compare again.
OGS and gmsh run as child processes; this process keeps its JSON-RPC stream on a private copy of
file descriptor 1, and anything a library prints goes to stderr.
"""
from __future__ import annotations

import os
import sys


def _protect_stdout():
    rpc_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = os.fdopen(rpc_fd, "w", buffering=1)


def main(root: str | None = None):
    _protect_stdout()
    import asyncio
    import base64
    import json
    from pathlib import Path

    import mcp_types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    from . import tools
    from .session import Session

    tools.WAIT.update({"run_status": 25.0, "compare": 25.0})  # below common client tool timeouts
    session = Session(root=Path(root or os.environ.get("THMSTUDIO_PROJECTS", Path.home() / "thmstudio_projects")))

    def doc(fn):
        return " ".join((fn.__doc__ or "").split())

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name=n, description=doc(fn), inputSchema=cls.model_json_schema())
            for n, (cls, fn) in tools.TOOLS.items()])

    async def call_tool(ctx, params):
        out = await asyncio.to_thread(tools.call, session, params.name, dict(params.arguments or {}))
        content = [types.TextContent(type="text", text=json.dumps(out, default=str, ensure_ascii=False))]
        for key in ("picture", "preview"):
            p = out.get(key)
            if isinstance(p, str) and p.endswith(".png") and Path(p).exists():
                content.append(types.ImageContent(type="image", mimeType="image/png",
                                                  data=base64.b64encode(Path(p).read_bytes()).decode()))
        return types.CallToolResult(content=content, isError=not out.get("ok", False))

    server = Server("geoai-thm-studio", on_list_tools=list_tools, on_call_tool=call_tool)

    async def run():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
