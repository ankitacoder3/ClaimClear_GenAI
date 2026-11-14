"""Print the tools each agent gets, straight from the live servers.

    python agents/toolkit/examples/show_agent_tools.py

Starts the three MCP servers over stdio (the servers' venv at <repo>/.venv), lists every
live tool with its server and read/write mark, then each agent's own tool list from
``claimclear_tools.agents.AGENT_TOOLS``. Tools of servers that don't exist yet
(the insurer portal) are shown as missing.
"""

from __future__ import annotations

import asyncio

from claimclear_tools import AGENT_TOOLS, ClaimClearToolkit
from claimclear_tools.agents import TOOL_SERVER, WRITE_TOOLS


async def main() -> None:
    async with ClaimClearToolkit(use_stubs=False) as tk:
        print("Live tools")
        for name in sorted(tk.tools):
            access = "write" if name in WRITE_TOOLS else "read"
            print(f"  {name:26} {TOOL_SERVER.get(name, '?'):18} {access}")
        print("\nTools per agent")
        for agent, wanted in AGENT_TOOLS.items():
            got = [t.name for t in tk.for_agent(agent)]
            missing = [n for n in wanted if n not in got]
            note = f"   (not available yet: {', '.join(missing)})" if missing else ""
            print(f"  {agent:20} {', '.join(got) or '-'}{note}")


if __name__ == "__main__":
    asyncio.run(main())
