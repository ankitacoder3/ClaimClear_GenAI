"""Assembling and compiling the ClaimClear graph G = (S, V, E, s0).

    START -> supervisor -> document_reader -> policy_analyst -> settlement_auditor -> critic
                ^                                                  ^     |  ^           |
                | replan (critic lost confidence)                  |  ask_user          |
                +--------------------------------------------------+-----+--------------+
                                         retry (critic disagreed)                       |
    critic -> explainer -> critic -> grievance_agent -> approval_gate -> portal_submit -> END
                  ^          |  (draft failed: plain verdict table)    |
                  +----------+                                         +-> END (declined)
    Any node can end the run early with an ``outcome`` (missing document, no policy, ...).

Two nodes pause with ``interrupt()``: ``ask_user`` (the engine's questions) and ``approval_gate`` (the person's
decision on the grievance). The state is checkpointed after every node, so a paused run can be resumed later,
inspected or forked (time travel). Use a durable checkpointer in production (``checkpoints.open_checkpointer``):
an in-memory one loses paused cases on restart.
"""

from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .agents import make_nodes
from .router import (route_after_analyst, route_after_auditor, route_after_critic, route_after_gate,
                     route_after_grievance, route_after_reader, route_after_supervisor)
from .services import Services
from .state import GraphState


def build_claimclear_graph(services: Services, checkpointer: Optional[BaseCheckpointSaver] = None):
    """Build and compile the graph. ``services.toolkit`` must stay open while the graph runs.

    Filing is impossible without a person: ``portal_submit`` is reachable only through ``approval_gate``, which
    waits for ``HumanApprovalGateway``, and ``portal_submit`` itself re-checks approval, token and hash.
    """
    g = StateGraph(GraphState)
    for name, fn in make_nodes(services).items():
        g.add_node(name, fn)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route_after_supervisor, ["document_reader", "settlement_auditor"])
    g.add_conditional_edges("document_reader", route_after_reader, ["policy_analyst", END])
    g.add_conditional_edges("policy_analyst", route_after_analyst, ["settlement_auditor", END])
    g.add_conditional_edges("settlement_auditor", route_after_auditor, ["critic", "ask_user", END])
    g.add_edge("ask_user", "settlement_auditor")
    g.add_conditional_edges("critic", route_after_critic,
                            ["settlement_auditor", "supervisor", "explainer", "grievance_agent", END])
    g.add_edge("explainer", "critic")
    g.add_conditional_edges("grievance_agent", route_after_grievance, ["approval_gate", END])
    g.add_conditional_edges("approval_gate", route_after_gate, ["portal_submit", END])
    g.add_edge("portal_submit", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())


def initial_state(case_id: str, *, user_id: Optional[str] = None, claim: Optional[dict] = None,
                  letter: Optional[dict] = None, max_revisions: Optional[int] = None) -> dict:
    """The input for ``graph.ainvoke``: the app supplies the case ID (and, until the document reader's
    LLM extraction is configured, the extracted claim and letter)."""
    state: dict = {"case_id": case_id}
    if user_id:
        state["user_id"] = user_id
    if claim is not None:
        state["claim"] = claim
    if letter is not None:
        state["letter"] = letter
    if max_revisions is not None:
        state["max_revisions"] = max_revisions
    return state
