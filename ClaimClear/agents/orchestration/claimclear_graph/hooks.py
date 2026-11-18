"""The two security hook points (Member 2's handover, section "Where Member 4's hooks attach").

==========  ==================================================  ==========================================
Hook        Where it attaches                                   What it knows / does here
==========  ==================================================  ==========================================
1           ``ToolNode(tools, awrap_tool_call=permission_hook(  the calling **agent**: refuses a tool outside
            agent))``, around each call an LLM agent makes       its ``AGENT_TOOLS`` row with ``NOT_ALLOWED``
2           ``ClaimClearToolkit(tool_interceptors=[...])``,      the **server**, tool and arguments: timing /
            around every MCP call (first is outermost)           audit log; may refuse by returning a message
==========  ==================================================  ==========================================

The deterministic nodes in ``agents/`` don't go through a ``ToolNode``; they get the same
least-privilege check from ``services.ScopedToolkit``. Hook 2 sees every call either way, because the
toolkit loads every MCP tool with the interceptors.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from claimclear_tools.agents import may_use
from claimclear_tools.results import ERROR_PREFIX
from langchain_core.messages import ToolMessage


def permission_hook(agent: str) -> Callable:
    """Hook 1, for ``ToolNode(..., awrap_tool_call=permission_hook(agent))``."""

    async def wrapper(request: Any, execute: Callable) -> Any:
        call = getattr(request, "tool_call", request)
        name, call_id = call.get("name"), call.get("id") or "call"
        if not may_use(agent, name):
            body = json.dumps({"code": "NOT_ALLOWED", "message": f"{agent} may not call {name}", "retryable": False})
            # Same text shape the MCP adapters use, so claimclear_tools.results.tool_error() parses it.
            return ToolMessage(content=f"{ERROR_PREFIX} {name}: {body}", tool_call_id=call_id, name=name, status="error")
        return await execute(request)

    return wrapper


def is_error_message(result: Any) -> bool:
    """Whether a tool result is an error: the message's own ``status`` field first (set by LangChain and the
    MCP adapters), then the MCP ``isError`` flag in the artifact, then the adapters' error text as a fallback."""
    if getattr(result, "status", None) == "error":
        return True
    artifact = getattr(result, "artifact", None)
    if isinstance(artifact, dict) and artifact.get("isError"):
        return True
    text = getattr(result, "content", "")
    return isinstance(text, str) and text.startswith(ERROR_PREFIX)


class AuditLog:
    """Hook 2: an interceptor that records every MCP call (server, tool, milliseconds, error?).

    Arguments are not logged: they hold claim data. Member 4 replaces ``sink`` with the scrubbed tracer.
    """

    def __init__(self, sink: Callable[[dict], None] | None = None):
        self.records: list[dict] = []
        self._sink = sink

    async def __call__(self, request: Any, handler: Callable) -> Any:
        t0 = time.perf_counter()
        result = await handler(request)
        rec_error = is_error_message(result)
        rec = {"server": getattr(request, "server_name", "?"), "tool": getattr(request, "name", "?"),
               "ms": round((time.perf_counter() - t0) * 1000, 1), "error": rec_error}
        self.records.append(rec)
        if self._sink:
            self._sink(rec)
        return result
