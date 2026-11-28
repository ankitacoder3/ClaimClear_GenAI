"""``GraphState``: the LangGraph state of one ClaimClear case.

It is Member 2's shared contract ``claimclear_contracts.CaseState`` (every field keeps the
**server's own shape**, so data flows from tool to tool without conversion) plus the few
fields the orchestration needs to route, loop and pause.

Integration note (merge of the two code bases)
----------------------------------------------
Member 3's first version defined its own ``CaseState`` with invented fields
(``claim_summary``, ``deductions``, ``DeductionItem`` ...). Those are gone: the graph now
uses the contract fields directly (``claim``, ``letter``, ``settlement``, ``row_audits``,
``letter_audit``, ``critic``, ``draft``, ``grievance``), and only the routing fields below are
added. The contract's ``pages`` field (full ``DocumentTextOut``) is deliberately left empty: the
document reader keeps a ``page_summary`` instead, so checkpoints stay small and untrusted document
text (hidden channels included) is never stored at rest. Never put policy limits, file paths, ``dataset_map.json`` or answer keys in the state.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional

from claimclear_contracts.state import CaseState, engine_case

# Values of ``GraphState["outcome"]``: how a run ended (the app shows the matching screen).
OUTCOME_GRIEVANCE_FILED = "grievance_filed"            # approved and filed (dry run until the mock portal exists)
OUTCOME_GRIEVANCE_DECLINED = "grievance_declined"      # the policyholder rejected the draft at the gate
OUTCOME_NO_GRIEVANCE = "no_grievance"                  # nothing disputable: the explanation is the answer
OUTCOME_NEEDS_INFORMATION = "needs_information"        # the engine can't settle it yet (open questions shown)
OUTCOME_MISSING_DOCUMENT = "missing_document"          # a page could not be read: ask for a better copy
OUTCOME_ASK_FOR_POLICY = "ask_user_for_policy"         # no policy schedule on record for the case
OUTCOME_POLICY_MISMATCH = "policy_mismatch"            # bill / letter / schedule name different policies
OUTCOME_INVALID_EXTRACTION = "invalid_extraction"      # the extracted claim is impossible (engine refused it)
OUTCOME_EXTRACTION_NEEDED = "extraction_needed"        # no claim/letter and no extractor configured
OUTCOME_CRITIC_BLOCKED = "critic_blocked"              # the draft failed the critic twice: nothing is shown
OUTCOME_TOOL_ERROR = "tool_error"                      # a tool error the graph cannot recover from

# Values of ``GraphState["critic_stage"]``: which review the critic does next.
STAGE_AUDIT_PENDING = "audit_pending"      # auditor finished -> critic re-checks the numbers
STAGE_AUDIT_PASSED = "audit_passed"
STAGE_AUDIT_FAILED = "audit_failed"
STAGE_DRAFT_READY = "draft_ready"          # explainer finished -> critic checks the words and figures
STAGE_DRAFT_PASSED = "draft_passed"
STAGE_DRAFT_FAILED = "draft_failed"


class GraphState(CaseState, total=False):
    # ---- documents (summary only: the text itself is never checkpointed) ------------------
    page_summary: dict[str, dict[str, Any]]      # document_id -> page counts, unreadable pages, flags, channel names
    # ---- run control ---------------------------------------------------------------------
    route: str                                   # the last node's routing signal (claimclear_tools.signals names)
    outcome: str                                 # how the run ended (OUTCOME_* above); empty while running
    revision_count: int                          # critic failures so far (hard loop guard)
    max_revisions: int                           # default 3: retry, replan, then fall back
    replan_reason: str                           # why the supervisor replanned (shown with the plan)
    replan_rows: list[str]                       # rows to re-test with every hypothesis after a replan
    # ---- critic loop ---------------------------------------------------------------------
    critic_stage: str                            # STAGE_* above
    critic_verdict: dict[str, Any]               # passed, confidence, critique, requires_replan, target_retry_node
    draft_attempt: int                           # 1 = full explanation, 2 = plain verdict table (fallback)
    # ---- user-facing text ----------------------------------------------------------------
    explanation: str                             # the plain-language explanation (draft sentences joined)
    explainer_mode: str                          # "free" for the Signature 2 OFF ablation; else fact-bound
    audit_table_markdown: str                    # one row per letter row: insurer vs policy amount, verdict, clause
    # ---- approval gate and filing --------------------------------------------------------
    approval_token: Optional[str]                # issued by the gate for grievance.text_sha256
    human_approved: bool
    submission: dict[str, Any]                   # insurer-portal FileGrievanceOut
    grievance_status: dict[str, Any]             # insurer-portal GrievanceStatusOut
    memory_grievance_id: Optional[str]           # claimclear_memory grievance record, when memory is on
    # ---- observability -------------------------------------------------------------------
    trace: Annotated[list[str], operator.add]    # one line per node step (append-only reducer)


__all__ = ["GraphState", "CaseState", "engine_case"] + [
    n for n in dir() if n.startswith(("OUTCOME_", "STAGE_"))]
