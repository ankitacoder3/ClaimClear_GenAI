"""Conditional edges of the ClaimClear graph.

Every decision reads a field a node wrote from a **tool result** (``route``, ``critic_stage``,
``letter_audit``), never model text, so the routing rules are plain tested code
(``claimclear_tools.signals`` names the routes).

The critic loop has two hard guards (Lecture 8, "bounded reflection"):

* ``revision_count >= max_revisions`` stops retrying the audit and explains the critic's own
  independent audit instead;
* a draft that fails twice ends the run (``critic_blocked``): nothing unchecked reaches the user.
"""

from __future__ import annotations

from typing import Literal

from claimclear_tools import signals
from langgraph.graph import END

from .state import (STAGE_AUDIT_FAILED, STAGE_AUDIT_PASSED, STAGE_DRAFT_FAILED, STAGE_DRAFT_PASSED, GraphState)


def _ended(state: GraphState) -> bool:
    return bool(state.get("outcome"))


def route_after_supervisor(state: GraphState) -> Literal["document_reader", "settlement_auditor"]:
    """A replan goes straight back to the auditor; a first plan starts with the documents."""
    return "settlement_auditor" if state.get("route") == "replan" else "document_reader"


def route_after_reader(state: GraphState) -> Literal["policy_analyst", "__end__"]:
    return END if _ended(state) else "policy_analyst"


def route_after_analyst(state: GraphState) -> Literal["settlement_auditor", "__end__"]:
    return END if _ended(state) else "settlement_auditor"


def route_after_auditor(state: GraphState) -> Literal["critic", "ask_user", "__end__"]:
    if _ended(state):
        return END
    return "ask_user" if state.get("route") == signals.ASK_USER else "critic"


def route_after_critic(state: GraphState) -> Literal["settlement_auditor", "supervisor", "explainer",
                                                     "grievance_agent", "__end__"]:
    """Retry, replan, explain, draft a grievance, or stop."""
    if _ended(state):
        return END
    stage = state.get("critic_stage")
    if stage == STAGE_AUDIT_PASSED:
        return "explainer"
    if stage == STAGE_AUDIT_FAILED:
        if state.get("revision_count", 0) >= state.get("max_revisions", 3):
            return "explainer"                     # loop guard: explain the critic's independent audit
        verdict = state.get("critic_verdict") or {}
        return "supervisor" if verdict.get("requires_replan") else "settlement_auditor"
    if stage == STAGE_DRAFT_FAILED:
        return "explainer"                         # attempt 2: the plain verdict table
    if stage == STAGE_DRAFT_PASSED:
        offer = signals.after_letter_audit(state.get("letter_audit") or {}) == signals.OFFER_GRIEVANCE
        return "grievance_agent" if offer else END
    return END


def route_after_grievance(state: GraphState) -> Literal["approval_gate", "__end__"]:
    """Only a drafted grievance goes on, to the approval gate (which pauses for the person)."""
    return "approval_gate" if state.get("grievance") and not _ended(state) else END


def route_after_gate(state: GraphState) -> Literal["portal_submit", "__end__"]:
    """Approved: file it. Rejected: the gate already set ``outcome = grievance_declined``."""
    return "portal_submit" if state.get("route") == "approved" and not _ended(state) else END
