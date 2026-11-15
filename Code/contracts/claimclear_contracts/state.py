"""``CaseState``: the LangGraph state for one case.

Each field holds a server's own output (or input) shape, so data flows from tool to
tool without conversion. ``FIELD_SHAPES`` says which schema each field follows, who
fills it and who reads it; a test checks every named schema exists in the exported
tool schemas (``tool_schemas.json``).

Never put in the state or a prompt: policy limits (the engine loads its own), file
paths, ``dataset_map.json``, the manifest or answer key, or held-out cases.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Optional, TypedDict


class Shape(NamedTuple):
    schema: Optional[str]      # a model in tool_schemas.json, or None for a shape defined here / by the app
    filled_by: str
    read_by: str
    note: str = ""


class CaseState(TypedDict, total=False):
    case_id: str                                  # case_[0-9a-f]{16}
    user_id: str                                  # the app's opaque user ID
    plan: dict[str, Any]                          # handoffs.Plan
    documents: list[dict[str, Any]]               # CaseDocumentsOut.documents
    pages: dict[str, dict[str, Any]]              # document_id -> DocumentTextOut
    claim: dict[str, Any]                         # settlement-engine ClaimIn
    letter: dict[str, Any]                        # settlement-engine LetterIn
    sources: dict[str, str]                       # field path -> span_id, e.g. "letter.rows[2].amount": "p1-s41"
    policy: dict[str, Any]                        # case-records PolicyOut (= settlement-engine PolicyIn)
    wording: dict[str, Any]                       # case-records WordingOut: ask for the user's wording if needed
    history: list[dict[str, Any]]                 # case-records PastClaimOut (= settlement-engine PastClaimIn)
    clauses: dict[str, dict[str, Any]]            # clause_id -> policy-kb get_clause result
    settlement: dict[str, Any]                    # settlement-engine SettlementOut
    row_audits: dict[str, dict[str, Any]]         # row_id -> settlement-engine RowAuditOut
    letter_audit: dict[str, Any]                  # settlement-engine LetterAuditOut
    questions: list[dict[str, Any]]               # settlement-engine QuestionOut
    answers: dict[str, Any]                       # question_id -> the user's answer (claimclear_tools.case.apply_answer)
    memory: dict[str, Any]                        # claimclear_memory context (empty without consent)
    security_flags: list[str]                     # set by Member 4's guardrails
    critic: dict[str, Any]                        # handoffs.CriticReport
    draft: dict[str, Any]                         # handoffs.ExplainerDraft
    grievance: dict[str, Any]                     # handoffs.GrievanceDraft


FIELD_SHAPES: dict[str, Shape] = {
    "case_id": Shape(None, "app (Member 4), at upload", "everyone", "pattern case_[0-9a-f]{16}"),
    "user_id": Shape(None, "app (Member 4), from the session", "memory"),
    "plan": Shape("Plan", "supervisor", "everyone; shown to the user"),
    "documents": Shape("DocumentInfoOut", "document reader <- list_case_documents", "document reader"),
    "pages": Shape("DocumentTextOut", "document reader <- get_document_text", "document reader, guardrails"),
    "claim": Shape("ClaimIn", "document reader (structured extraction)", "auditor, critic"),
    "letter": Shape("LetterIn", "document reader (structured extraction)", "auditor, critic, grievance agent"),
    "sources": Shape(None, "document reader", "UI highlighting, critic", "{field path: span_id}"),
    "policy": Shape("PolicyOut", "policy analyst <- get_policy", "auditor, critic"),
    "wording": Shape("WordingOut", "policy analyst <- get_policy_wording",
                     "supervisor (asks for the user's wording when wording_needed), explainer"),
    "history": Shape("PastClaimOut", "policy analyst <- get_claim_history", "auditor, critic"),
    "clauses": Shape("ClauseOut", "policy analyst <- get_clause / clauses_for_rule", "explainer, critic"),
    "settlement": Shape("SettlementOut", "auditor <- expected_settlement", "auditor, explainer, critic"),
    "row_audits": Shape("RowAuditOut", "auditor <- reproduce_deduction", "explainer, critic, grievance agent"),
    "letter_audit": Shape("LetterAuditOut", "critic <- audit_settlement_letter", "critic, explainer"),
    "questions": Shape("QuestionOut", "from settlement and row_audits", "supervisor -> interrupt()"),
    "answers": Shape(None, "user, via interrupt()", "auditor (re-run)", "applied with claimclear_tools.case.apply_answer"),
    "memory": Shape(None, "supervisor <- claimclear_memory context()", "everyone; critic takes figures"),
    "security_flags": Shape(None, "guardrails (Member 4)", "supervisor"),
    "critic": Shape("CriticReport", "critic", "supervisor"),
    "draft": Shape("ExplainerDraft", "explainer", "critic, output guardrails"),
    "grievance": Shape("GrievanceDraft", "grievance agent", "approval gate (Member 4)"),
}


def engine_case(state: CaseState) -> dict[str, Any]:
    """The ``case`` argument for every settlement-engine tool, straight from the state."""
    return {"claim": state["claim"], "policy": state["policy"], "history": state.get("history", [])}
