"""Which agent may use which tool.

The plan requires that every agent gets only the tools it needs. This table is
the single place that says so; ``ClaimClearToolkit.for_agent`` uses it, and
Member 4's permission hook can use it too.
"""

from __future__ import annotations

from .config import CASE_RECORDS, INSURER_PORTAL, POLICY_KB, SETTLEMENT_ENGINE

# tool -> server
TOOL_SERVER: dict[str, str] = {
    "list_case_documents": CASE_RECORDS,
    "get_document_text": CASE_RECORDS,
    "get_policy": CASE_RECORDS,
    "get_policy_wording": CASE_RECORDS,
    "get_claim_history": CASE_RECORDS,
    "expected_settlement": SETTLEMENT_ENGINE,
    "reproduce_deduction": SETTLEMENT_ENGINE,
    "audit_settlement_letter": SETTLEMENT_ENGINE,
    "list_hypotheses": SETTLEMENT_ENGINE,
    "search_clauses": POLICY_KB,
    "get_clause": POLICY_KB,
    "clauses_for_rule": POLICY_KB,
    "list_policies": POLICY_KB,
    "register_uploaded_wording": POLICY_KB,     # app only (the upload ingestion job), in no agent's list
    "grievance_status": INSURER_PORTAL,
    "file_grievance": INSURER_PORTAL,
}

# Write tools. Only the grievance agent may hold one, and only behind the approval gate.
WRITE_TOOLS = frozenset({"file_grievance", "register_uploaded_wording"})
APP_ONLY_TOOLS = frozenset({"register_uploaded_wording"})   # the app calls these; never give them to an agent

DOCUMENT_READER = "document_reader"
POLICY_ANALYST = "policy_analyst"
SETTLEMENT_AUDITOR = "settlement_auditor"
CRITIC = "critic"
EXPLAINER = "explainer"
GRIEVANCE_AGENT = "grievance_agent"
SUPERVISOR = "supervisor"
SINGLE_AGENT = "single_agent"    # the C1 baseline: every read tool, same budget
QA_AGENT = "qa_agent"            # the chat window's question answering (claimclear_graph.qa): read only

AGENT_TOOLS: dict[str, tuple[str, ...]] = {
    DOCUMENT_READER: ("list_case_documents", "get_document_text"),
    POLICY_ANALYST: ("get_policy", "get_policy_wording", "get_claim_history", "list_policies", "search_clauses", "get_clause",
                     "clauses_for_rule"),
    SETTLEMENT_AUDITOR: ("expected_settlement", "list_hypotheses", "reproduce_deduction"),
    CRITIC: ("audit_settlement_letter", "expected_settlement", "get_clause"),
    EXPLAINER: ("get_clause", "clauses_for_rule"),
    GRIEVANCE_AGENT: ("grievance_status", "file_grievance"),
    SUPERVISOR: (),
    QA_AGENT: ("list_case_documents", "get_document_text", "search_clauses", "get_clause", "clauses_for_rule",
               "grievance_status"),
    SINGLE_AGENT: ("list_case_documents", "get_document_text", "get_policy", "get_policy_wording", "get_claim_history",
                   "expected_settlement", "list_hypotheses", "reproduce_deduction", "audit_settlement_letter",
                   "list_policies", "search_clauses", "get_clause", "clauses_for_rule"),
}


def tools_for(agent: str) -> tuple[str, ...]:
    """Tool names an agent may use. Raises ``KeyError`` for an unknown agent."""
    return AGENT_TOOLS[agent]


def may_use(agent: str, tool: str) -> bool:
    """For a permission hook: is ``agent`` allowed to call ``tool``?"""
    return tool in AGENT_TOOLS.get(agent, ())
