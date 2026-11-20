"""Conversion between the MCP schemas (pydantic) and the engine's dataclasses.

``to_*`` functions turn validated tool inputs into engine objects. ``*_payload``
functions go the other way, from engine objects (for example a dataset case)
to the JSON a client sends; tests and the CLI use them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from engine.dataset import Case
from engine.models import (
    BillLine,
    Claim,
    LetterRow,
    PastClaim,
    Policy,
    SettlementLetter,
)

from .schemas import CaseIn, ClaimIn, LetterIn, PastClaimIn, PolicyIn


# --------------------------------------------------------------------------- schema -> engine


def to_claim(c: ClaimIn) -> Claim:
    return Claim(
        claim_id=c.claim_id,
        policy_no=c.policy_no,
        admission=c.admission,
        discharge=c.discharge,
        lines=tuple(
            BillLine(
                line_id=line.line_id,
                description=line.description,
                amount=line.amount,
                qty=line.qty,
                rate=line.rate,
                gst_pct=line.gst_pct,
                non_payable=line.non_payable,
                category=line.category,
                date=line.date,
            )
            for line in c.lines
        ),
        diagnosis=c.diagnosis,
        procedure=c.procedure,
        discount=c.discount,
        printed_total=c.printed_total,
        condition_type=c.condition_type,
        room_priced_by_category=dict(c.room_priced_by_category),
        hospital_gstin=c.hospital_gstin,
        bill_numbers=tuple(n[:60] for n in c.bill_numbers),
    )


def to_policy(p: PolicyIn) -> Policy:
    return Policy(
        policy_no=p.policy_no,
        sum_insured=p.sum_insured,
        period_start=p.period_start,
        period_end=p.period_end,
        first_inception=p.first_inception,
        holder=p.holder,
        insurer=p.insurer,
        product=p.product,
        wording_uin=p.wording_uin,
        wording_source=p.wording_source,
    )


def to_past_claim(h: PastClaimIn) -> PastClaim:
    return PastClaim(
        claim_id=h.claim_id,
        policy_no=h.policy_no,
        admission=h.admission,
        status=h.status,
        settled_amount=h.settled_amount,
        diagnosis=h.diagnosis,
        procedure=h.procedure,
    )


def to_case(case: CaseIn) -> tuple[Claim, Policy, list[PastClaim]]:
    return to_claim(case.claim), to_policy(case.policy), [to_past_claim(h) for h in case.history]


def to_letter(lt: LetterIn) -> SettlementLetter:
    return SettlementLetter(
        letter_id=lt.letter_id,
        letter_type=lt.letter_type,
        claimed_amount=lt.claimed_amount,
        rows=tuple(LetterRow(r.row_id, r.particulars, r.amount, r.reason, r.kind) for r in lt.rows),
        paid_amount=lt.paid_amount,
        copay_amount=lt.copay_amount,
        rejection_reason=lt.rejection_reason,
    )


# --------------------------------------------------------------------------- engine -> JSON payload


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _opt(value: Any) -> Any:
    return None if value is None else (value.value if hasattr(value, "value") else value)


def claim_payload(c: Claim) -> dict:
    return {
        "claim_id": c.claim_id,
        "policy_no": c.policy_no,
        "admission": c.admission.isoformat() if c.admission else None,
        "discharge": c.discharge.isoformat() if c.discharge else None,
        "lines": [
            {
                "line_id": line.line_id,
                "description": line.description,
                "amount": str(line.amount),
                "qty": str(line.qty),
                "rate": _money(line.rate),
                "gst_pct": str(line.gst_pct),
                "non_payable": line.non_payable,
                "category": _opt(line.category),
                "date": line.date.isoformat() if line.date else None,
            }
            for line in c.lines
        ],
        "diagnosis": c.diagnosis,
        "procedure": c.procedure,
        "discount": str(c.discount),
        "printed_total": _money(c.printed_total),
        "condition_type": _opt(c.condition_type),
        "room_priced_by_category": {k.value: v for k, v in c.room_priced_by_category.items()},
        "hospital_gstin": c.hospital_gstin,
        "bill_numbers": list(c.bill_numbers),
    }


def policy_payload(p: Policy) -> dict:
    return {
        "policy_no": p.policy_no,
        "sum_insured": str(p.sum_insured),
        "period_start": p.period_start.isoformat(),
        "period_end": p.period_end.isoformat(),
        "first_inception": p.first_inception.isoformat(),
        "holder": p.holder,
        "insurer": p.insurer,
        "product": p.product,
        "wording_uin": p.wording_uin,
        "wording_source": p.wording_source,
    }


def past_claim_payload(h: PastClaim) -> dict:
    return {
        "claim_id": h.claim_id,
        "policy_no": h.policy_no,
        "admission": h.admission.isoformat(),
        "status": h.status,
        "settled_amount": str(h.settled_amount),
        "diagnosis": h.diagnosis,
        "procedure": h.procedure,
    }


def case_payload(case: Case) -> dict:
    """A dataset ``Case`` as the ``case`` argument of the tools."""
    return {
        "claim": claim_payload(case.claim),
        "policy": policy_payload(case.policy),
        "history": [past_claim_payload(h) for h in case.history],
    }


def letter_payload(lt: SettlementLetter) -> dict:
    """A ``SettlementLetter`` as the ``letter`` argument of the tools."""
    return {
        "letter_id": lt.letter_id,
        "letter_type": lt.letter_type,
        "claimed_amount": str(lt.claimed_amount),
        "rows": [
            {"row_id": r.row_id, "particulars": r.particulars, "amount": str(r.amount), "reason": r.reason,
             "kind": _opt(r.kind)}
            for r in lt.rows
        ],
        "paid_amount": str(lt.paid_amount),
        "copay_amount": _money(lt.copay_amount),
        "rejection_reason": lt.rejection_reason,
    }
