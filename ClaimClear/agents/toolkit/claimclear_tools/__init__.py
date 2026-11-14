"""claimclear_tools: the agents' side of the ClaimClear MCP servers (for Member 3).

Install in the **agents'** environment (Python 3.14 recommended)::

    pip install -e agents/toolkit

Main entry points:

* ``ClaimClearToolkit``: connect to every server, get tools per agent, typed calls.
* ``agents``: who may use which tool (``AGENT_TOOLS``, ``may_use``).
* ``results``: ``structured``, ``tool_error``, ``ClaimClearToolError``.
* ``signals``: tool result -> graph route (``after_settlement``, ``after_row_audit``...).
* ``case``: ``build_case``, ``apply_answer``.
* ``critic``: ``allowed_figures``, ``unsupported_figures``, ``wording_for``.
* ``config``: ``connections`` (stdio or HTTP, from environment variables).

``results``, ``signals``, ``case``, ``critic``, ``agents`` and ``config`` have no
third-party dependencies; ``ClaimClearToolkit`` and ``stubs`` need
``langchain-mcp-adapters``.
"""

from . import agents, case, critic, results, signals
from .agents import AGENT_TOOLS, may_use, tools_for
from .case import apply_answer, build_case
from .config import connections, endpoints
from .results import ClaimClearToolError, ToolErrorInfo, structured, tool_error

__version__ = "0.1.0"

__all__ = [
    "ClaimClearToolkit", "AGENT_TOOLS", "ClaimClearToolError", "ToolErrorInfo",
    "agents", "apply_answer", "build_case", "case", "connections", "critic", "endpoints", "may_use",
    "results", "signals", "structured", "tool_error", "tools_for",
]


def __getattr__(name: str):
    # Imported lazily so the pure helpers work without langchain-mcp-adapters installed.
    if name == "ClaimClearToolkit":
        from .toolkit import ClaimClearToolkit
        return ClaimClearToolkit
    raise AttributeError(name)
