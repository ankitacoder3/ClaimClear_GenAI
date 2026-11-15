import json
from decimal import Decimal

from engine import Status, compute_settlement
from factories import claim, line, policy, worked_example_lines


def test_amounts_reconcile(rules):
    r = compute_settlement(claim(worked_example_lines()), policy(), rules)
    assert r.claimed_amount - r.total_deductions - r.copay_amount == r.payable_amount


def test_every_deduction_has_a_fact_and_a_rule(rules):
    r = compute_settlement(claim(worked_example_lines()), policy(), rules)
    for d in r.deductions:
        f = r.fact(d.fact_id)
        assert f is not None and f.amount == d.amount
        assert d.rule_ref and d.formula


def test_core_facts_are_present(rules):
    r = compute_settlement(claim(worked_example_lines()), policy(), rules)
    for fact_id in ("F-CLAIMED", "F-WAITING", "F-ROOM-CAP", "F-PROP-RATIO", "F-PROP-LINKED",
                    "F-PROP-EXCLUDED", "F-ADMISSIBLE", "F-COPAY", "F-SI-REMAINING", "F-PAYABLE"):
        assert r.fact(fact_id) is not None, fact_id


def test_fact_ids_are_stable(rules):
    a = compute_settlement(claim(worked_example_lines()), policy(), rules)
    b = compute_settlement(claim(worked_example_lines()), policy(), rules)
    assert [f.fact_id for f in a.facts] == [f.fact_id for f in b.facts]
    assert a.to_dict() == b.to_dict()


def test_printed_total_mismatch_is_reported(rules):
    c = claim([line("L01", "Surgeon fee", 10000)], printed_total=25000)
    r = compute_settlement(c, policy(), rules)
    assert r.fact("F-TOTAL-MISMATCH").amount == Decimal("15000.00")
    assert r.warnings


def test_printed_total_within_a_rupee_is_fine(rules):
    r = compute_settlement(claim([line("L01", "Surgeon fee", 10000)], printed_total=10000.5), policy(), rules)
    assert r.fact("F-TOTAL-MISMATCH") is None


def test_discount_reduces_the_claim(rules):
    r = compute_settlement(claim([line("L01", "Surgeon fee", 10000)], discount=1000), policy(), rules)
    assert r.claimed_amount == Decimal("9000.00")


def test_admission_outside_policy_period_asks_for_the_right_schedule(rules):
    r = compute_settlement(claim([line("L01", "Surgeon fee", 10000)], admission="2026-08-01"), policy(), rules)
    assert r.status == Status.NEEDS_INFORMATION
    assert r.questions[0].question_id == "Q-POLICY-PERIOD"


def test_result_is_json_serialisable(rules):
    r = compute_settlement(claim(worked_example_lines()), policy(), rules)
    data = json.loads(json.dumps(r.to_dict()))
    assert data["payable_amount"] == 94905.0
    assert data["status"] == "computed"
    assert data["lines"][0]["category"] == "room"
