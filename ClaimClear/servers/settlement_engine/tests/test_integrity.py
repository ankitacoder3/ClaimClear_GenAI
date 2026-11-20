"""Document integrity (engine/integrity.py) and rejections confirmed by the bill's own inconsistencies.

The four synthetic fakes of the dev split (syn-dev-004, -006, -012, -015) are reproduced with the factories; the
other 38 dev cases raise no finding (checked when the module was written: tests/test_integrity.py only pins the rules).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from engine import Status, Verdict, audit_letter, compute_settlement, default_rules, reproduce_letter_row
from engine import integrity
from engine.engine import read_lines
from engine.matcher import classify_rejection, classify_row
from engine.models import RowKind
from factories import claim, letter, line, policy

RULES = default_rules()


def stay(**kw):
    return claim([line("L01", "Semi-private room", 13500, qty=3, rate=4500, date="2026-01-19"),
                  line("L02", "Surgeon fee - laparoscopic appendectomy", 27000, date="2026-01-20"),
                  line("L03", "Operation theatre charges", 17000, date="2026-01-20"),
                  line("L04", "Pharmacy - inpatient medicines", 9700, date="2026-01-21")], **kw)


def codes(c):
    return [(f.code, f.definite) for f in integrity.check(c, read_lines(c))]


def rejected(reason, claimed):
    return letter([], claimed=claimed, paid=0, letter_type="rejection", rejection_reason=reason)


# --------------------------------------------------------------------------- the checks


def test_an_ordinary_bill_raises_nothing():
    assert codes(stay()) == []


def test_discharge_before_admission():
    assert codes(stay(admission="2026-04-12", discharge="2026-04-09")) == [("discharge_before_admission", True)]


def test_room_and_icu_days_beyond_the_stay():
    c = claim([line("L01", "Semi-private ward", 40500, qty=9, rate=4500, date="2026-06-02"),
               line("L02", "ICU charges", 48000, qty=4, rate=12000, date="2026-06-02")],
              admission="2026-06-02", discharge="2026-06-05")
    assert codes(c) == [("room_days_exceed_stay", True)]


def test_one_extra_day_is_allowed_for_counting_both_ends():
    c = claim([line("L01", "Semi-private room", 18000, qty=4, rate=4500)], admission="2026-01-19", discharge="2026-01-22")
    assert codes(c) == []


def test_every_inpatient_line_dated_outside_the_stay():
    c = stay(admission="2026-03-10", discharge="2026-03-13")          # header moved; the lines still say January
    found = integrity.check(c, read_lines(c))
    assert [(f.code, f.definite) for f in found] == [("inpatient_lines_outside_stay", True)]
    assert integrity.line_dated_stay(found) == (c.lines[0].date, c.lines[2].date)


def test_only_some_lines_outside_is_not_definite():
    c = stay(admission="2026-01-20", discharge="2026-01-22")          # the room line starts a day earlier
    assert codes(c) == [("some_inpatient_lines_outside", False)]


def test_gstin_format():
    assert codes(replace(stay(), hospital_gstin="00ABCD1234E1Z")) == [("gstin_malformed", True)]
    assert codes(replace(stay(), hospital_gstin="00AABFT5678K1Z2")) == []      # the dataset's placeholder: format ok
    assert codes(replace(stay(), hospital_gstin="-")) == []                    # none printed


def test_one_stay_on_two_invoices_is_reported_not_deducted():
    c = replace(stay(), bill_numbers=("KSH-26-058210", "KSH-26-058297"))
    found = integrity.check(c, read_lines(c))
    assert [(f.code, f.definite) for f in found] == [("split_invoices", False)]
    assert found[0].inputs == {"bill_numbers": ["KSH-26-058210", "KSH-26-058297"], "combined_total": "67200"}
    r = compute_settlement(c, policy(), RULES)
    assert r.status == Status.COMPUTED and r.payable_amount == compute_settlement(stay(), policy(), RULES).payable_amount
    assert any(w.startswith("Check the bill: one hospital stay") for w in r.warnings)
    # one invoice number, or the same number twice, is not a split
    assert codes(replace(stay(), bill_numbers=("KSH-1",))) == []
    assert codes(replace(stay(), bill_numbers=("KSH-1", "KSH-1 "))) == []


def test_a_split_bill_never_confirms_a_rejection():
    c = replace(stay(), bill_numbers=("A-1", "A-2"))
    row = audit_letter(rejected("Under the fraud condition of the policy, the claim is repudiated.", "67200"), c,
                       policy(), RULES).rows[0]
    assert row.verdict != Verdict.MATCHES_POLICY          # not definite: no evidence that the documents are false


def test_findings_are_facts_and_warnings_never_deductions():
    r = compute_settlement(replace(stay(), hospital_gstin="BAD"), policy(), RULES)
    facts = [f for f in r.facts if f.kind == "integrity"]
    assert facts and facts[0].inputs["code"] == "gstin_malformed" and facts[0].rule_ref == "fraud"
    assert any("inconsistent" in w for w in r.warnings) and r.status == Status.COMPUTED and r.payable_amount > 0


def test_impossible_dates_stop_and_ask_for_the_real_ones():
    r = compute_settlement(stay(admission="2026-04-12", discharge="2026-04-09"), policy(), RULES)
    assert r.status == Status.NEEDS_INFORMATION and [q.question_id for q in r.questions] == ["Q-ADMISSION"]


# --------------------------------------------------------------------------- confirming a rejection


def test_not_genuine_reasons_are_recognised():
    for reason in ("Our investigation found charges for services that were not provided.",
                   "The hospital is not registered with the local authority.",
                   "The hospital could not confirm the admission, so the claim is repudiated.",
                   "Under the fraud condition of the policy, the claim is repudiated."):
        assert classify_row(reason) == RowKind.NOT_GENUINE, reason
    assert classify_rejection("Not payable: the 30-day initial waiting period is not completed.") == RowKind.WAITING_PERIOD


def test_a_not_genuine_rejection_is_confirmed_by_impossible_dates():
    c = stay(admission="2026-04-12", discharge="2026-04-09")
    claimed = compute_settlement(c, policy(), RULES).claimed_amount
    lt = rejected("Discharge before admission; the hospital could not confirm the admission.", claimed)
    a = reproduce_letter_row(lt, c, policy(), RULES, [], "REJECTION")
    assert a.verdict == Verdict.MATCHES_POLICY and a.method == "not_genuine_documents" and a.rule_ref == "fraud"
    audit = audit_letter(lt, c, policy(), RULES)
    assert audit.policy_payable == 0 and audit.disputable_amount == 0 and audit.questions == []


def test_a_not_genuine_rejection_without_evidence_stays_unverifiable():
    c = stay()
    claimed = compute_settlement(c, policy(), RULES).claimed_amount
    a = reproduce_letter_row(rejected("The claim is not genuine.", claimed), c, policy(), RULES, [], "REJECTION")
    assert a.verdict != Verdict.MATCHES_POLICY                         # no inconsistency: nothing confirms it


def test_a_waiting_period_rejection_is_tested_on_the_lines_own_dates():
    pol = policy(start="2026-01-01", end="2026-12-31", inception="2026-01-01")      # first taken on 1 Jan 2026
    c = stay(admission="2026-03-10", discharge="2026-03-13")    # header after the 30 days; the lines say 19-21 Jan
    assert compute_settlement(c, pol, RULES).status == Status.COMPUTED              # on the header: payable
    claimed = compute_settlement(c, pol, RULES).claimed_amount
    lt = rejected("Treatment of an illness in the first 30 days of cover is excluded (initial waiting period).", claimed)
    a = reproduce_letter_row(lt, c, pol, RULES, [], "REJECTION")
    assert a.verdict == Verdict.MATCHES_POLICY and a.method == "waiting_period_on_line_dates"
    assert "19-Jan-2026" in a.explanation and not a.explanation.endswith("..")
    assert audit_letter(lt, c, pol, RULES).policy_payable == 0


def test_without_the_letter_saying_illness_nothing_is_assumed():
    pol = policy(start="2026-01-01", end="2026-12-31", inception="2026-01-01")
    c = stay(admission="2026-03-10", discharge="2026-03-13")
    claimed = compute_settlement(c, pol, RULES).claimed_amount
    lt = rejected("Initial waiting period: the admission was within 30 days of the policy start.", claimed)
    a = reproduce_letter_row(lt, c, pol, RULES, [], "REJECTION")
    assert a.method != "waiting_period_on_line_dates"          # illness or accident is unknown: not confirmed


def test_evidence_never_explains_an_ordinary_deduction_row():
    # A settlement letter that deducts the whole claim on one unlabelled row, on a bill with a malformed GSTIN:
    # the "not genuine" evidence must not be used to call that deduction right.
    from factories import row
    c = replace(stay(), hospital_gstin="BAD")
    claimed = compute_settlement(c, policy(), RULES).claimed_amount
    lt = letter([row("R1", "Other deductions", claimed)], claimed=claimed, paid=Decimal(0))
    a = reproduce_letter_row(lt, c, policy(), RULES, [], "R1")
    assert a.method not in ("not_genuine_documents", "waiting_period_on_line_dates")
    assert a.verdict != Verdict.MATCHES_POLICY
