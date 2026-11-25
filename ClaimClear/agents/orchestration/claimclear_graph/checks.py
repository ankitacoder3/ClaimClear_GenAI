"""The critic's checks, as pure functions (no LangGraph, no I/O), so they are unit-tested on their own.

Two reviews, both deterministic ("the model proposes, code decides"):

1. **Audit review** (after the settlement auditor): the critic re-runs the whole letter through
   ``audit_settlement_letter`` independently, and every row verdict and policy amount the auditor
   reported must agree with it (``disputable_total`` failure otherwise).
2. **Draft review** (after the explainer): every rupee figure must come from a tool
   (``figure_not_from_engine``), each row's sentence must use the wording allowed for its verdict
   (``verdict_wording``), no forbidden phrase (``forbidden_phrase``), and every cited clause must be a
   clause policy-kb returned (``clause_not_found``) and none may be cited when the wording on file is
   another product's (``clause_from_other_wording``).

Failures use the ``claimclear_contracts.CriticFailure`` check names, so the report is a valid
``CriticReport``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from claimclear_contracts.verdicts import FORBIDDEN_PHRASES, wording_for
from claimclear_tools.critic import allowed_figures, unsupported_figures

AMOUNT_TOLERANCE = 0.01


def inr(value) -> str:
    """₹ amount as the explanation writes it: ``₹8,522.86``, ``₹95,617.50``, ``₹6,000``."""
    if value is None:
        return "₹—"
    d = Decimal(str(value))
    return f"₹{d:,.0f}" if d == d.to_integral_value() else f"₹{d:,.2f}"


def failure(check: str, detail: str) -> dict:
    return {"check": check, "detail": detail[:500]}


# --------------------------------------------------------------------------- audit review


def review_audit(row_audits: dict[str, dict], letter_audit: dict) -> list[dict]:
    """The auditor's rows against the critic's independent ``audit_settlement_letter`` run."""
    out = []
    independent = {r["row_id"]: r for r in letter_audit.get("rows", [])}
    for row_id, row in row_audits.items():
        other = independent.get(row_id)
        if other is None:
            out.append(failure("disputable_total", f"{row_id}: audited by the auditor but absent from the letter audit"))
            continue
        if row.get("verdict") != other.get("verdict"):
            out.append(failure("disputable_total",
                               f"{row_id}: auditor says {row.get('verdict')}, independent audit says {other.get('verdict')}"))
        a, b = row.get("policy_amount"), other.get("policy_amount")
        if (a is None) != (b is None) or (a is not None and abs(float(a) - float(b)) > AMOUNT_TOLERANCE):
            out.append(failure("disputable_total", f"{row_id}: policy amount {a} vs independent {b}"))
    missing = sorted(set(independent) - set(row_audits))
    if missing:
        out.append(failure("disputable_total", f"rows not audited by the auditor: {', '.join(missing)}"))
    return out


def unfinished_rows(row_audits: dict[str, dict]) -> list[str]:
    """Rows that ended ``not_verifiable`` without every hypothesis tested: worth a replan."""
    return [k for k, r in row_audits.items() if r.get("verdict") == "not_verifiable" and r.get("exhaustive") is False]


def confidence(letter_audit: dict) -> float:
    """Share of the letter's deducted rupees the engine could verify (1.0 = every rupee checked)."""
    total = sum(float(r.get("insurer_amount") or 0) for r in letter_audit.get("rows", []))
    if total <= 0:
        return 1.0
    unverified = float(letter_audit.get("unverified_amount") or 0)
    return round(max(0.0, 1.0 - unverified / total), 2)


# --------------------------------------------------------------------------- draft review


def forbidden_phrases(text: str) -> list[str]:
    low = (text or "").lower()
    return [p for p in FORBIDDEN_PHRASES if p in low]


def review_draft(text: str, row_sentences: dict[str, str], letter_audit: dict, *, settlement: Optional[dict] = None,
                 row_audits: Iterable[dict] = (), cited_clause_ids: Iterable[str] = (),
                 known_clause_ids: Iterable[str] = (), remembered: Iterable = (),
                 clauses_quotable: bool = True) -> list[dict]:
    """All draft checks. ``row_sentences`` maps row_id -> the sentence that states that row's verdict.

    ``clauses_quotable`` false (case-records ``cite_clauses``: the wording on file is another product's): any
    cited clause fails, even one policy-kb returned, because it is not the user's policy."""
    out = []
    allowed = allowed_figures(settlement, list(row_audits), letter_audit, remembered)
    for fig in unsupported_figures(text, allowed):
        out.append(failure("figure_not_from_engine", f"₹{fig} is not a figure any tool produced"))
    independent = {r["row_id"]: r for r in letter_audit.get("rows", [])}
    for row_id, sentence in row_sentences.items():
        row = independent.get(row_id)
        if row is not None and wording_for(row) not in sentence:
            out.append(failure("verdict_wording", f"{row_id}: must say '{wording_for(row)}'"))
    for phrase in forbidden_phrases(text):
        out.append(failure("forbidden_phrase", f"'{phrase}' may never be used"))
    known = set(known_clause_ids)
    for cid in set(cited_clause_ids) - known:
        out.append(failure("clause_not_found", f"clause {cid} was cited but policy-kb never returned it"))
    if not clauses_quotable:
        for cid in sorted(set(cited_clause_ids) & known):
            out.append(failure("clause_from_other_wording",
                               f"clause {cid} is from a wording that is not this policy's; it may not be cited"))
    return out
