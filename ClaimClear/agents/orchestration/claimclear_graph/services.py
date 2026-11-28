"""What the graph's nodes need from outside the state: the toolkit, memory, extraction, rewriting.

``Services`` is handed to ``build_claimclear_graph`` once; nodes read it from their closure, so
nothing un-serialisable ever goes into the checkpointed state.

**Least privilege for deterministic nodes.** The nodes call the toolkit's typed methods directly
(``await tk.expected_settlement(case)``), which LangGraph's ``ToolNode`` hook never sees. So every
node gets a ``ScopedToolkit``: a view of the toolkit that refuses any tool outside that agent's row
of ``claimclear_tools.agents.AGENT_TOOLS`` with the same ``NOT_ALLOWED`` error the hook-1
``permission_hook`` returns, for typed calls, ``call()``, ``tool()``, ``tools`` and ``for_agent()``.

**Retries.** A tool error the server marks ``retryable`` (e.g. policy-kb's ``UPSTREAM_UNAVAILABLE`` when the
embedding provider is down) is retried with exponential back-off (``retry_attempts``, ``retry_backoff``);
every other error is raised at once, so the graph's error edges handle it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from claimclear_tools.agents import TOOL_SERVER, may_use
from claimclear_tools.results import RETRY_LATER, STOP, ClaimClearToolError, ToolErrorInfo

log = logging.getLogger("claimclear.graph")


def retryable(exc: ClaimClearToolError) -> bool:
    return exc.info.retryable or exc.info.action == RETRY_LATER


class ScopedToolkit:
    """A per-agent view of ``ClaimClearToolkit``: tools outside the agent's list raise ``NOT_ALLOWED``;
    retryable tool errors are retried with back-off."""

    def __init__(self, toolkit: Any, agent: str, retry_attempts: int = 2, retry_backoff: float = 0.5):
        self._tk = toolkit
        self.agent = agent
        self.retry_attempts = retry_attempts
        self.retry_backoff = retry_backoff
        self.retries = 0                                  # how many retries this view made (for tests and logs)

    def _refuse(self, tool: str) -> ClaimClearToolError:
        return ClaimClearToolError(ToolErrorInfo(tool, "NOT_ALLOWED", f"{self.agent} may not call {tool}", False, STOP))

    async def _with_retry(self, name: str, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        for attempt in range(self.retry_attempts + 1):
            try:
                return await fn(*args, **kwargs)
            except ClaimClearToolError as exc:
                if not retryable(exc) or attempt == self.retry_attempts:
                    raise
                self.retries += 1
                delay = self.retry_backoff * (2 ** attempt)
                log.info("%s: %s %s, retry %d in %.1fs", self.agent, name, exc.info.code, attempt + 1, delay)
                await asyncio.sleep(delay)

    async def call(self, name: str, args: dict) -> dict:
        if not may_use(self.agent, name):
            raise self._refuse(name)
        return await self._with_retry(name, self._tk.call, name, args)

    def tool(self, name: str) -> Any:
        """One LangChain tool, only if this agent may use it."""
        if not may_use(self.agent, name):
            raise self._refuse(name)
        return self._tk.tool(name)

    def for_agent(self, agent: str) -> list:
        """Only this view's own agent: a node can't ask for another agent's tools."""
        if agent != self.agent:
            raise self._refuse(f"for_agent({agent})")
        return self._tk.for_agent(agent)

    @property
    def tools(self) -> dict:
        """The live tools this agent may use (never the whole toolkit)."""
        return {k: v for k, v in getattr(self._tk, "tools", {}).items() if may_use(self.agent, k)}

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._tk, name)
        if name in TOOL_SERVER:
            if not may_use(self.agent, name):
                async def refused(*_a, **_k):
                    raise self._refuse(name)
                return refused

            async def with_retry(*args, **kwargs):
                return await self._with_retry(name, attr, *args, **kwargs)
            return with_retry
        return attr


@dataclass
class Services:
    """Everything the nodes use besides the state.

    * ``toolkit``: an open ``claimclear_tools.ClaimClearToolkit`` (or any object with the same typed
      async methods, e.g. the offline ``testing.ReplayToolkit``).
    * ``memory_store``: a ``claimclear_memory.MemoryStore``; per-user memory is used only when the
      state has a ``user_id`` and that user consented (otherwise ``NoMemory``, which stores nothing).
    * ``extractor``: the document reader's extraction, ``async (toolkit, case_id, documents, pages) -> {"claim",
      "letter", "sources"?}`` (``extraction.llm_extractor``). When ``None``, the claim and letter must be in the
      initial state (the app's upload step or a labelled development stand-in). Only visible text may reach a model.
    * ``rewriter`` / ``language``: ``async (text, language) -> text`` rewriting the explanation into plain language
      or another language (``language.llm_rewriter``); the critic checks the rewritten text.
    * ``max_revisions``: critic failures allowed before the graph falls back (loop guard): the 1st
      audit failure retries the auditor, the 2nd replans, the 3rd stops the loop.
    * ``retry_attempts`` / ``retry_backoff``: retries for retryable tool errors (seconds, doubled each time).
    """

    toolkit: Any
    memory_store: Any = None
    extractor: Optional[Callable[..., Awaitable[dict]]] = None
    rewriter: Optional[Callable[[str, str], Awaitable[str]]] = None
    language: str = "en"
    max_revisions: int = 3
    retry_attempts: int = 2
    retry_backoff: float = 0.5

    def tools_for(self, agent: str) -> ScopedToolkit:
        return ScopedToolkit(self.toolkit, agent, self.retry_attempts, self.retry_backoff)

    def memory_for(self, user_id: Optional[str]) -> Any:
        """``UserMemory`` with consent, else ``NoMemory`` (or ``None`` without a store or user)."""
        if self.memory_store is None or not user_id:
            return None
        return self.memory_store.session_memory(user_id)
