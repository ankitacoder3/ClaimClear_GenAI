"""ClaimClear settlement engine.

Computes, in plain tested Python, what an Arogya Sanjeevani policy says should
be paid on a reimbursement claim. No LLM is involved: the model proposes, this
code decides. See ``README.md`` in the parent folder.
"""

from .engine import compute_settlement, read_lines
from .identifiers import canonical_policy_no, has_lookalikes, same_policy
from .hypotheses import HYPOTHESES, CaseContext, Hypothesis, list_hypotheses
from .matcher import audit_letter, classify_row, reproduce_letter_row, reproduce_row
from .models import (
    BillLine,
    Category,
    Claim,
    ConditionType,
    Deduction,
    DeductionKind,
    Fact,
    HypothesisMatch,
    LetterAudit,
    LetterRow,
    LineView,
    PastClaim,
    Policy,
    PolicyRules,
    Question,
    RowAudit,
    RowKind,
    SettlementLetter,
    SettlementResult,
    Status,
    Verdict,
)
from .rules import RULE_REFS, default_rules, load_rules, rules_from_dict

__all__ = [
    "compute_settlement",
    "read_lines",
    "audit_letter",
    "classify_row",
    "reproduce_row",
    "reproduce_letter_row",
    "list_hypotheses",
    "HYPOTHESES",
    "CaseContext",
    "Hypothesis",
    "BillLine",
    "Category",
    "Claim",
    "ConditionType",
    "Deduction",
    "DeductionKind",
    "Fact",
    "HypothesisMatch",
    "LetterAudit",
    "LetterRow",
    "LineView",
    "PastClaim",
    "Policy",
    "PolicyRules",
    "Question",
    "RowAudit",
    "RowKind",
    "SettlementLetter",
    "SettlementResult",
    "Status",
    "Verdict",
    "RULE_REFS",
    "default_rules",
    "load_rules",
    "rules_from_dict",
    "canonical_policy_no",
    "has_lookalikes",
    "same_policy",
]
