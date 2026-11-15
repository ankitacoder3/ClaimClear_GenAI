"""Checks the critic runs on a draft reply.

1. **Every rupee figure in the draft must come from a tool.** ``allowed_figures``
   collects every amount the tools produced (facts, deductions, row audits, the
   letter summary, and figures inside engine-written text such as "₹2,000 a
   day"); ``unsupported_figures`` lists the draft's figures that match none of them.
2. **Wording must follow the verdict.** ``wording_for`` gives the phrase allowed
   for each row; ``WORDING`` is the table. Both come from ``claimclear_contracts.verdicts``,
   shared with the servers' side, so there is one wording table.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from claimclear_contracts.verdicts import VERDICT_WORDING, wording_for  # noqa: F401  re-exported

RUPEE = re.compile(r"(?:₹|Rs\.?|INR)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
TOLERANCE = Decimal("0.01")

WORDING = VERDICT_WORDING      # the table lives in the shared contracts


def rupee_figures(text: str) -> list[Decimal]:
    """Every rupee amount written in ``text`` (₹1,28,350 / Rs. 6000 / INR 4,583.93)."""
    out = []
    for m in RUPEE.finditer(text or ""):
        try:
            out.append(Decimal(m.group(1).replace(",", "")))
        except InvalidOperation:
            continue
    return out


def _num(value) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def allowed_figures(settlement: Optional[dict] = None, rows: Iterable[dict] = (),
                    letter_audit: Optional[dict] = None, remembered: Iterable = ()) -> set[Decimal]:
    """Every amount the tools produced for this case, plus ``remembered`` amounts from earlier engine runs
    (``claimclear_memory`` context ``["figures"]``) when the explanation may mention them."""
    allowed: set[Decimal] = set()
    texts: list[str] = []

    def add(*values) -> None:
        for v in values:
            n = _num(v)
            if n is not None:
                allowed.add(abs(n))

    def take_settlement(s: dict) -> None:
        add(s.get("claimed_amount"), s.get("total_deductions"), s.get("admissible_amount"),
            s.get("copay_amount"), s.get("payable_amount"))
        for f in s.get("facts", []):
            add(f.get("amount"))
            texts.extend([f.get("text", ""), f.get("formula", "")])
        for d in s.get("deductions", []):
            add(d.get("amount"))
            texts.extend([d.get("description", ""), d.get("formula", "")])
        for line in s.get("lines", []):
            add(line.get("amount"), line.get("gst"))

    def take_row(r: dict) -> None:
        add(r.get("insurer_amount"), r.get("policy_amount"), r.get("difference"))
        for m in r.get("matches", []):
            add(m.get("amount"))
            texts.append(m.get("detail", ""))
        texts.extend([r.get("explanation", ""), r.get("particulars", "")])  # particulars quote the insurer's letter

    if settlement:
        take_settlement(settlement)
    rows = list(rows)
    for r in rows:
        take_row(r)
    if letter_audit:
        add(letter_audit.get("policy_payable"), letter_audit.get("insurer_paid"), letter_audit.get("gap"),
            letter_audit.get("unverified_amount"), letter_audit.get("disputable_amount"),
            letter_audit.get("overpaid_amount"), letter_audit.get("letter_arithmetic_gap"))
        for r in letter_audit.get("rows", []):
            take_row(r)
        if letter_audit.get("settlement"):
            take_settlement(letter_audit["settlement"])
        texts.extend(letter_audit.get("policy_deductions_not_on_letter", []))
    add(*remembered)
    for t in texts:
        allowed.update(rupee_figures(t))
    return allowed


def unsupported_figures(draft: str, allowed: set[Decimal]) -> list[Decimal]:
    """Rupee figures in ``draft`` that no tool produced (within ₹0.01). Empty means the draft passes."""
    return [f for f in rupee_figures(draft) if not any(abs(f - a) <= TOLERANCE for a in allowed)]
