"""Small builders for hand-made test cases."""

from __future__ import annotations

from engine import BillLine, Category, Claim, ConditionType, LetterRow, PastClaim, Policy, SettlementLetter
from engine.money import D, to_date


def policy(si=300000, start="2025-07-15", end="2026-07-14", inception="2022-07-15", no="P-TEST") -> Policy:
    return Policy(policy_no=no, sum_insured=D(si), period_start=to_date(start), period_end=to_date(end),
                  first_inception=to_date(inception))


def line(line_id, description, amount, qty=1, rate=None, gst=0, non_payable=None, category=None, date=None) -> BillLine:
    return BillLine(line_id=line_id, description=description, amount=D(amount), qty=D(qty),
                    rate=None if rate is None else D(rate), gst_pct=D(gst),
                    non_payable=non_payable, category=category, date=None if date is None else to_date(date))


def claim(lines, admission="2026-01-19", discharge="2026-01-22", policy_no="P-TEST", claim_id="C-TEST",
          diagnosis="Acute appendicitis", procedure="", discount=0, printed_total=None,
          condition_type: ConditionType | None = None, room_priced_by_category: dict[Category, bool] | None = None
          ) -> Claim:
    return Claim(claim_id=claim_id, policy_no=policy_no, admission=to_date(admission), discharge=None if discharge is None else to_date(discharge),
                 lines=tuple(lines), diagnosis=diagnosis, procedure=procedure, discount=D(discount),
                 printed_total=None if printed_total is None else D(printed_total),
                 condition_type=condition_type, room_priced_by_category=room_priced_by_category or {})


def past(claim_id, admission, settled, policy_no="P-TEST", status="settled", diagnosis="", procedure="") -> PastClaim:
    return PastClaim(claim_id=claim_id, policy_no=policy_no, admission=to_date(admission), status=status,
                     settled_amount=D(settled), diagnosis=diagnosis, procedure=procedure)


def row(row_id, particulars, amount, kind=None, reason="") -> LetterRow:
    return LetterRow(row_id=row_id, particulars=particulars, amount=D(amount), reason=reason, kind=kind)


def letter(rows, claimed, paid, copay=None, letter_type="settlement", rejection_reason="", letter_id="L-TEST"
           ) -> SettlementLetter:
    return SettlementLetter(letter_id=letter_id, letter_type=letter_type, claimed_amount=D(claimed),
                            rows=tuple(rows), paid_amount=D(paid),
                            copay_amount=None if copay is None else D(copay), rejection_reason=rejection_reason)


def worked_example_lines(room_rate=7000, nights=3):
    """The room-rent case from section 3 of the ClaimClear plan (no GST)."""
    return [
        line("L01", "Private room", room_rate * nights, qty=nights, rate=room_rate),
        line("L02", "Nursing and duty doctor charges", 4500),
        line("L03", "Surgeon fee - laparoscopic cholecystectomy", 32000),
        line("L04", "Anaesthetist fee", 11000),
        line("L05", "Operation theatre charges", 22000),
        line("L06", "Consultant visits", 5400),
        line("L07", "Laboratory investigations", 7200),
        line("L08", "MRCP", 6500),
        line("L09", "Pharmacy - inpatient medicines", 12900),
        line("L10", "Laparoscopic clips and retrieval bag", 4800),
    ]
