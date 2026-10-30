"""thmstudio: chat with the agent, run the verification cases, start the MCP server, list examples."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _chat(args):
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY in the environment to chat (the key is read from the environment only).")
    from agents import Runner, set_tracing_disabled
    from agents.exceptions import OutputGuardrailTripwireTriggered

    from .agent.build import build_agent
    from .agent.sdk import history_after_tripwire, run_config
    from .session import Session

    set_tracing_disabled(True)
    session = Session(root=Path(args.projects).expanduser())
    agent = build_agent(args.model)
    history: list = []
    loop = asyncio.new_event_loop()  # one loop for the session: the model client is bound to it
    print("GeoAI-THM Studio (built on OpenGeoSys). Free for noncommercial use. Type 'quit' to stop.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except EOFError:
            break
        if text.lower() in ("quit", "exit", "q"):
            break
        history.append({"role": "user", "content": text})
        session.user_texts.append(text)
        for attempt in range(2):
            try:
                result = loop.run_until_complete(Runner.run(agent, history, context=session, max_turns=args.max_turns,
                                                            run_config=run_config()))
                history = result.to_input_list()
                print(f"\nstudio> {result.final_output}")
                break
            except OutputGuardrailTripwireTriggered as e:
                bad = e.guardrail_result.output.output_info.get("unsupported_numbers", [])
                history = history_after_tripwire(e, history)
                history.append({"role": "user", "content": "Your answer quoted numbers that are not on the answer card "
                                f"or in my inputs: {', '.join(bad)}. Rewrite it using only numbers from answer_card."})
        if session.state == "REPORTED":
            page = session.dir / "report.html"
            if page.exists() and not args.no_open:
                import webbrowser
                webbrowser.open(page.as_uri())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="thmstudio", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat", help="talk to the modelling agent")
    c.add_argument("--model", default="gpt-6.1-terra", help="OpenAI model, e.g. gpt-6.1-terra or gpt-6-luna")
    c.add_argument("--projects", default="~/thmstudio_projects")
    c.add_argument("--max-turns", type=int, default=60)
    c.add_argument("--no-open", action="store_true", help="do not open the results page")
    v = sub.add_parser("verify", help="run the verification cases (thmstudio verify --help for options)",
                       add_help=False)
    v.add_argument("rest", nargs=argparse.REMAINDER)
    m = sub.add_parser("mcp", help="start the MCP stdio server")
    m.add_argument("--projects", default="~/thmstudio_projects")
    sub.add_parser("examples", help="list the examples")
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["verify"]:  # every option goes to the verification runner
        from .verify import main as vmain
        raise SystemExit(vmain(argv[1:]))
    a = ap.parse_args(argv)
    if a.cmd == "chat":
        _chat(a)
    elif a.cmd == "verify":
        from .verify import main as vmain
        raise SystemExit(vmain(a.rest))
    elif a.cmd == "mcp":
        from .mcp_server import main as mmain
        mmain(str(Path(a.projects).expanduser()))
    else:
        from .tools import _examples
        for e in _examples():
            print(f"{e['id']:22s} {e['configuration']:20s} {e['title']}")


if __name__ == "__main__":
    main()
