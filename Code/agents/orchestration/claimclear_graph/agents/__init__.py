"""The ClaimClear agents, one module per agent (each exposes ``make(services) -> {node_name: async fn}``).

==================  ==============================  =========================================================
Module              Nodes                           Tools (``claimclear_tools.agents.AGENT_TOOLS`` row)
==================  ==============================  =========================================================
supervisor          supervisor                      none
document_reader     document_reader                 list_case_documents, get_document_text
policy_analyst      policy_analyst                  get_policy, get_policy_wording, get_claim_history,
                                                    search_clauses
settlement_auditor  settlement_auditor, ask_user    expected_settlement, reproduce_deduction
critic              critic                          audit_settlement_letter
explainer           explainer                       clauses_for_rule
grievance           grievance_agent, approval_gate, file_grievance, grievance_status (portal_submit only)
                    portal_submit
==================  ==============================  =========================================================

No node computes a rupee figure: every amount comes from the settlement engine, and the critic checks that the
text only quotes them.
"""

from __future__ import annotations

from typing import Any, Callable

from ..services import Services
from . import critic, document_reader, explainer, grievance, policy_analyst, settlement_auditor, supervisor

MODULES = (supervisor, document_reader, policy_analyst, settlement_auditor, critic, explainer, grievance)


def make_nodes(services: Services) -> dict[str, Callable[..., Any]]:
    """Every node function, closed over ``services``, keyed by node name."""
    nodes: dict = {}
    for module in MODULES:
        nodes.update(module.make(services))
    return nodes
