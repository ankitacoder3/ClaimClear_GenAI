"""What the insurer's letter itself settles (engine/matcher.py, 18 Nov 2026):

* a claim the insurer **paid** with no waiting-period row has had its condition accepted as covered, so the open
  "which waiting-period list?" question doesn't stop the audit (syn-dev-017);
* rows that can't be checked cost the policyholder a full rupee each when the letter took its co-pay **before** them,
  not (100 - co-pay)%, so nothing is left looking disputable (gen-dev-b4331d).
"""

from __future__ import annotations

from decimal import Decimal

from engine import Status, Verdict, audit_letter, compute_settlement, default_rules, reproduce_letter_row
from factories import claim, letter, line, policy, row

RULES = default_rules()
D = Decimal


def listed():
    """A meniscus tear (a listed illness) 26 months after first inception: 24- or 36-month list unknown."""
    pol = policy(si=500000, start="2026-04-20", end="2027-04-19", inception="2024-04-20")
    c = claim([line("L01", "Surgeon fee - arthroscopic meniscal repair", 60000),
               line("L02", "Gloves, masks and syringes", 1800, non_payable=True)],
              admission="2026-06-22", discharge="2026-06-24", diagnosis="Medial meniscus tear, right knee",
              procedure="Arthroscopic meniscal repair")
    return pol, c


def test_the_engine_alone_asks_which_list():
    pol, c = listed()
    r = compute_settlement(c, pol, RULES)
    assert r.status == Status.NEEDS_INFORMATION and [q.question_id for q in r.questions] == ["Q-CONDITION-TYPE"]


def test_a_paid_claim_is_audited_on_the_insurers_acceptance():
    pol, c = listed()
    payable = D("57000.00")                                   # (61,800 - 1,800) less 5% co-pay
    lt = letter([row("R1", "Non-payable items: gloves, masks, syringes", 1800)], claimed=61800, paid=payable,
                copay=3000)
    audit = audit_letter(lt, c, pol, RULES)
    assert audit.settlement.status == Status.COMPUTED and audit.policy_payable == payable
    assert all(a.verdict == Verdict.MATCHES_POLICY for a in audit.rows) and audit.questions == []
    assert any(f.fact_id == "F-CONDITION-FROM-LETTER" and "listed illness short" in f.text
               for f in audit.settlement.facts)


def test_nothing_is_assumed_for_a_rejection_a_waiting_period_row_or_no_payment():
    pol, c = listed()
    for lt in (letter([], claimed=61800, paid=0, letter_type="rejection", rejection_reason="Waiting period of 36 months"),
               letter([row("R1", "Waiting period not completed", 61800)], claimed=61800, paid=0),
               letter([row("R1", "Non-payable items", 1800)], claimed=61800, paid=0)):
        a = reproduce_letter_row(lt, c, pol, RULES, [], lt.rows[0].row_id if lt.rows else "REJECTION")
        assert a.verdict == Verdict.NOT_VERIFIABLE, lt


def _pharmacy_case(copay_first: bool):
    c = claim([line("L01", "Surgeon fee", 50000), line("L02", "Pharmacy - inpatient medicines", 10000)])
    claimed = D(60000)
    cut = D(4300)                                             # part of the grouped pharmacy line: can't be checked
    copay = (claimed * D("0.05")) if copay_first else ((claimed - cut) * D("0.05"))
    lt = letter([row("R1", "Pharmacy items not payable as per annexure", cut)], claimed=claimed,
                paid=claimed - cut - copay, copay=copay)
    return audit_letter(lt, c, policy(), RULES)


def test_rows_that_cannot_be_checked_after_the_copay_count_in_full():
    audit = _pharmacy_case(copay_first=True)
    assert next(a for a in audit.rows if a.row_id == "R1").verdict == Verdict.NOT_VERIFIABLE
    assert audit.unverified_amount == D("4300.00") and audit.disputable_amount == 0


def test_rows_that_cannot_be_checked_before_the_copay_count_net_of_it():
    audit = _pharmacy_case(copay_first=False)
    assert audit.unverified_amount == D("4085.00") and audit.disputable_amount == 0
