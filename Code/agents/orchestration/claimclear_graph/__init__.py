"""claimclear_graph: ClaimClear's multi-agent orchestration (Member 3) on Member 2's MCP servers.

    from claimclear_tools import ClaimClearToolkit
    from claimclear_graph import Services, build_claimclear_graph, initial_state, HumanApprovalGateway

    async with ClaimClearToolkit() as tk:                       # stdio servers, or CLAIMCLEAR_MCP_MODE=http
        graph = build_claimclear_graph(Services(toolkit=tk))
        cfg = {"configurable": {"thread_id": case_id}}
        state = await graph.ainvoke(initial_state(case_id, claim=claim, letter=letter), cfg)
        gate = HumanApprovalGateway(graph)
        if await gate.is_paused_for_approval(cfg):              # paused at the approval_gate node
            state = await gate.approve_and_resume(cfg)          # or gate.reject(cfg)

Modules: ``state`` (GraphState = contracts CaseState + routing fields), ``services`` (toolkit, memory,
per-agent ScopedToolkit), ``nodes`` (the agents), ``router`` (conditional edges), ``checks`` (critic
checks), ``plan`` (the visible plan), ``gateway`` (human approval), ``hooks`` (security hook points 1/2),
``extraction`` (the document reader's LLM extraction), ``language`` (plain-language / translated explanations),
``checkpoints`` (durable checkpointers), ``agents`` (one module per agent), ``graph`` (assembly).
"""

from .checkpoints import open_checkpointer
from .gateway import HumanApprovalGateway, issue_token
from .graph import build_claimclear_graph, initial_state
from .hooks import AuditLog, permission_hook
from .services import ScopedToolkit, Services
from .state import GraphState

__version__ = "0.3.0"

__all__ = ["AuditLog", "GraphState", "HumanApprovalGateway", "ScopedToolkit", "Services", "build_claimclear_graph",
           "initial_state", "issue_token", "open_checkpointer", "permission_hook"]
