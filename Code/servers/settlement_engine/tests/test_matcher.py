"""Verdict logic of the matcher on hand-made letters."""

import json
from decimal import Decimal

import pytest

from engine import (CaseContext, ConditionType, RowKind, Verdict, audit_letter, classify_row, compute_settlement,
                    reproduce_letter_row, reproduce_row)
from factories import claim, letter, line, policy, row, worked_example_lines


def ctx_for(c, p, rules, lt=None):
    return CaseContext(c, p, rules, [], compute_settlement(c, p, rules), lt)


# --- classification ---------------------------------------------------------------------


@pytest.mark.parametrize("text, kind", [
    ("Room rent above eligible limit (₹2,000 a day for 3 days)", RowKind.ROOM_RENT),
    ("GST on room rent above eligible limit", RowKind.ROOM_GST),
    ("Proportionate deduction on associated medical expenses (₹5,000 / ₹7,000)", RowKind.PROPORTIONATE),
    ("Non-payable items: gloves, masks, IV sets", RowKind.NON_PAYABLE),
    ("Cataract limit: admissible ₹30,000 for the right eye", RowKind.CATARACT),
    ("ICU charges above eligible limit", RowKind.ICU),
    ("Co-payment 5%", RowKind.COPAY),
    ("Waiting period not completed", RowKind.WAITING_PERIOD),
    ("Sum insured exhausted", RowKind.SUM_INSURED),
    ("Other deductions", RowKind.UNSPECIFIED),
])
def test_classify_row(text, kind):
    assert classify_row(text) == kind


def test_reason_used_when_particulars_say_nothing():
    assert classify_row("Deduction 3", "Listed as non-payable items under the policy") == RowKind.NON_PAYABLE


# --- verdicts on single rows ------------------------------------------------------------


def test_matches_policy(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    a = reproduce_row(ctx, row("R1", "Room rent above eligible limit", 6000))
    assert a.verdict == Verdict.MATCHES_POLICY and a.method == "room_rent_policy" and a.difference == 0


def test_within_one_rupee_matches(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    assert reproduce_row(ctx, row("R1", "Proportionate deduction", 21400.90)).verdict == Verdict.MATCHES_POLICY
    assert reproduce_row(ctx, row("R1", "Proportionate deduction", 21401.50)).verdict != Verdict.MATCHES_POLICY


def test_single_wrong_method_identified(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    a = reproduce_row(ctx, row("R3", "Proportionate deduction on associated medical expenses", 30371.43))
    assert a.verdict == Verdict.DOES_NOT_MATCH_POLICY
    assert a.method == "prop_on_all_lines"
    assert a.policy_amount == Decimal("21400.00") and a.difference == Decimal("8971.43")
    assert a.policy_fact_ids == ["F-D-PROPORTIONATE"]
    assert not a.questions


def test_equivalent_methods_are_merged(rules):
    # no ICU and no non-payables: 'every non-room line', '... incl. ICU' and '... incl. non-payables' are one calculation
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    a = reproduce_row(ctx, row("R3", "Proportionate deduction", 30371.43))
    assert {m.hypothesis_id for m in a.matches} >= {"prop_on_all_lines", "prop_on_all_lines_incl_icu"}
    assert a.method == "prop_on_all_lines"


def test_real_tie_asks_one_question(rules):
    lines = [line("L01", "Private room", 7000, qty=1, rate=7000), line("L02", "Surgeon fee", 14000),
             line("L03", "Pharmacy - inpatient medicines", 7000), line("L04", "Laboratory investigations", 7000)]
    ctx = ctx_for(claim(lines), policy(), rules)
    # pharmacy and diagnostics are both 7,000, so both variants give (14,000 + 7,000) x 2/7 = 6,000
    a = reproduce_row(ctx, row("R1", "Proportionate deduction", 6000))
    assert a.verdict == Verdict.DOES_NOT_MATCH_POLICY
    assert a.method is None
    assert a.questions and a.questions[0].question_id == "Q-TIE-R1"
    assert a.difference == Decimal("2000.00")


def test_no_match_asks_for_a_breakdown(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    a = reproduce_row(ctx, row("R1", "Proportionate deduction", 12345))
    assert a.verdict == Verdict.NOT_VERIFIABLE and a.exhaustive
    assert a.questions[0].question_id == "Q-BREAKDOWN-R1"


def test_partial_test_suggests_a_replan(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    r = row("R3", "Proportionate deduction", 30371.43)
    first = reproduce_row(ctx, r, hypothesis_ids=["prop_incl_pharmacy"])
    assert first.verdict == Verdict.NOT_VERIFIABLE
    assert not first.exhaustive and not first.questions
    assert "proportionate_policy" in first.tested            # the correct method is always tested
    assert "prop_on_all_lines" in first.explanation          # names what is left to test
    second = reproduce_row(ctx, r)                           # the replan: test everything
    assert second.method == "prop_on_all_lines"


def test_insurer_deducted_less_than_the_policy(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    a = reproduce_row(ctx, row("R1", "Room rent above eligible limit", 3000))
    assert a.verdict == Verdict.DOES_NOT_MATCH_POLICY and a.method == "room_cap_pct_only"
    assert a.difference == Decimal("-3000.00") and not a.over_deducted


def test_kind_given_by_the_caller_wins(rules):
    ctx = ctx_for(claim(worked_example_lines()), policy(), rules)
    a = reproduce_row(ctx, row("R1", "Deduction A", 6000, kind=RowKind.ROOM_RENT))
    assert a.kind_source == "input" and a.verdict == Verdict.MATCHES_POLICY


# --- unspecified rows -------------------------------------------------------------------


def test_unspecified_row_equal_to_a_policy_deduction(rules):
    c = claim([line("L01", "Surgeon fee", 20000), line("L02", "Consumables - gloves", 1500, non_payable=True)])
    lt = letter([row("R1", "Other deductions", 1500)], 21500, 19000, 1000)
    audit = audit_letter(lt, c, policy(si=500000), rules)
    assert audit.letter_arithmetic_gap == Decimal("0.00")
    r1 = audit.row("R1")
    assert r1.verdict == Verdict.MATCHES_POLICY and r1.method == "non_payable_policy"
    assert audit.policy_deductions_not_on_letter == []


def test_unspecified_row_does_not_reuse_a_kind_already_on_the_letter(rules):
    c = claim([line("L01", "Surgeon fee", 20000), line("L02", "Consumables - gloves", 1500, non_payable=True)])
    lt = letter([row("R1", "Non-payable items", 1500), row("R2", "Other deductions", 1500)], 21500, 17575, 925)
    audit = audit_letter(lt, c, policy(si=500000), rules)
    assert audit.row("R1").verdict == Verdict.MATCHES_POLICY
    assert audit.row("R2").verdict == Verdict.NOT_VERIFIABLE


# --- whole-letter summary ---------------------------------------------------------------


def worked_letter(prop=30371.43, copay=4546.43, paid=86382.14):
    return letter([row("R1", "Room rent above eligible limit", 6000),
                   row("R2", "Proportionate deduction on associated medical expenses", prop)],
                  127300, paid, copay)


def test_worked_example_letter(rules):
    audit = audit_letter(worked_letter(), claim(worked_example_lines()), policy(), rules)
    assert [r.verdict for r in audit.rows] == [Verdict.MATCHES_POLICY, Verdict.DOES_NOT_MATCH_POLICY,
                                               Verdict.METHOD_MATCHES]
    assert audit.policy_payable == Decimal("94905.00")
    assert audit.disputable_amount == Decimal("8522.86")      # the plan's figure
    assert audit.unverified_amount == Decimal("0.00")
    assert audit.letter_arithmetic_gap == Decimal("0.00")


def test_correct_letter_has_nothing_to_dispute(rules):
    lt = letter([row("R1", "Room rent above eligible limit", 6000), row("R2", "Proportionate deduction", 21400)],
                127300, 94905, 4995)
    audit = audit_letter(lt, claim(worked_example_lines()), policy(), rules)
    assert all(r.verdict == Verdict.MATCHES_POLICY for r in audit.rows)
    assert audit.disputable_amount == Decimal("0.00") and not audit.questions


def test_overpayment_is_never_disputable(rules):
    lt = letter([row("R1", "Room rent above eligible limit", 3000)], 127300, 118085, 6215)
    audit = audit_letter(lt, claim(worked_example_lines()), policy(), rules)
    assert audit.letter_arithmetic_gap == Decimal("0.00")
    assert audit.disputable_amount == Decimal("0.00")
    assert audit.overpaid_amount == Decimal("23180.00")     # 1,18,085 - 94,905
    assert any("Proportionate" in d for d in audit.policy_deductions_not_on_letter)


def test_letter_that_does_not_add_up(rules):
    audit = audit_letter(worked_letter(paid=85382.14), claim(worked_example_lines()), policy(), rules)
    assert audit.letter_arithmetic_gap == Decimal("1000.00")
    assert any("does not add up" in w for w in audit.warnings)
    assert audit.disputable_amount == Decimal("9522.86")      # the slip is in the gap too


def test_claimed_amount_mismatch_is_warned(rules):
    lt = letter([row("R1", "Room rent above eligible limit", 6000)], 130000, 117800, 6200)
    audit = audit_letter(lt, claim(worked_example_lines()), policy(), rules)
    assert any("claimed amount" in w for w in audit.warnings)


def test_needs_information_gives_no_verdicts(rules):
    lines = worked_example_lines() + [line("L11", "Platelet transfusion", 8500)]
    lt = letter([row("R1", "Proportionate deduction", 30000)], 135800, 100000, 5000)
    audit = audit_letter(lt, claim(lines), policy(), rules)
    assert all(r.verdict == Verdict.NOT_VERIFIABLE and r.policy_amount is None for r in audit.rows)
    assert audit.disputable_amount is None and audit.policy_payable is None
    assert audit.questions[0].question_id == "Q-ROOM-PRICING"


def test_correct_rejection_matches_policy(rules):
    p = policy(si=1000000, start="2026-02-01", end="2027-01-31", inception="2026-02-01")
    c = claim([line("L01", "Surgeon fee", 30000)], admission="2026-02-12", discharge="2026-02-15",
              condition_type=ConditionType.ILLNESS)
    lt = letter([], 30000, 0, letter_type="rejection",
                rejection_reason="Admitted within the 30-day waiting period from policy inception.")
    audit = audit_letter(lt, c, p, rules)
    assert audit.row("REJECTION").verdict == Verdict.MATCHES_POLICY
    assert audit.disputable_amount == Decimal("0.00")


def test_rejection_without_a_known_reason_is_not_verifiable(rules):
    lt = letter([], 127300, 0, letter_type="rejection", rejection_reason="Claim not admissible.")
    audit = audit_letter(lt, claim(worked_example_lines()), policy(), rules)
    r = audit.row("REJECTION")
    assert r.kind == RowKind.UNSPECIFIED and r.verdict == Verdict.NOT_VERIFIABLE
    assert audit.disputable_amount == Decimal("0.00")
    assert audit.unverified_amount == audit.gap


def test_audit_is_json_serialisable(rules):
    audit = audit_letter(worked_letter(), claim(worked_example_lines()), policy(), rules)
    data = json.loads(json.dumps(audit.to_dict()))
    assert data["disputable_amount"] == 8522.86
    assert data["rows"][1]["method"] == "prop_on_all_lines"


# --- one row in the context of its letter -----------------------------------------------


def test_reproduce_letter_row_matches_the_full_audit(rules):
    c, p = claim(worked_example_lines()), policy()
    full = audit_letter(worked_letter(), c, p, rules)
    for r in full.rows:
        one = reproduce_letter_row(worked_letter(), c, p, rules, row_id=r.row_id)
        assert one.to_dict() == r.to_dict()


def test_reproduce_letter_row_uses_the_other_rows(rules):
    c = claim([line("L01", "Surgeon fee", 20000), line("L02", "Consumables - gloves", 1500, non_payable=True)])
    lt = letter([row("R1", "Non-payable items", 1500), row("R2", "Other deductions", 1500)], 21500, 17575, 925)
    assert reproduce_letter_row(lt, c, policy(si=500000), rules, row_id="R2").verdict == Verdict.NOT_VERIFIABLE


def test_reproduce_letter_row_unknown_row(rules):
    with pytest.raises(KeyError):
        reproduce_letter_row(worked_letter(), claim(worked_example_lines()), policy(), rules, row_id="R9")
