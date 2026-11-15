from decimal import Decimal

from engine import DeductionKind, compute_settlement
from engine import calculators as calc
from factories import claim, line, past, policy, worked_example_lines


def test_copay_rounds_half_up(rules):
    assert calc.copay(Decimal("91678.57"), rules.copay_pct) == Decimal("4583.93")
    assert calc.copay(Decimal("100650"), rules.copay_pct) == Decimal("5032.50")


def test_copay_comes_after_every_other_deduction(rules):
    r = compute_settlement(claim(worked_example_lines()), policy(), rules)
    assert r.admissible_amount == Decimal("99900.00")
    assert r.copay_amount == Decimal("4995.00")          # 5% of 99,900, not of the 1,27,300 bill
    assert r.payable_amount == Decimal("94905.00")


def test_payable_capped_at_sum_insured_left(rules):
    history = [past("H1", "2025-09-01", 280000)]
    r = compute_settlement(claim([line("L01", "Surgeon fee", 50000)]), policy(si=300000), rules, history)
    assert r.fact("F-SI-REMAINING").amount == Decimal("20000.00")
    assert r.deduction(DeductionKind.SUM_INSURED_EXHAUSTED).amount == Decimal("27500.00")
    assert r.payable_amount == Decimal("20000.00")


def test_claims_from_another_policy_year_do_not_count(rules):
    history = [past("H1", "2025-03-01", 280000)]          # before period_start 2025-07-15
    r = compute_settlement(claim([line("L01", "Surgeon fee", 50000)]), policy(si=300000), rules, history)
    assert r.deduction(DeductionKind.SUM_INSURED_EXHAUSTED) is None
    assert r.payable_amount == Decimal("47500.00")


def test_unsettled_and_other_policy_claims_do_not_count(rules):
    history = [past("H1", "2025-09-01", 280000, status="rejected"),
               past("H2", "2025-09-01", 280000, policy_no="OTHER")]
    assert calc.remaining_sum_insured(policy(si=300000), history) == Decimal(300000)


def test_same_claim_in_history_is_not_counted_against_itself(rules):
    history = [past("C-TEST", "2026-01-19", 47500)]
    assert calc.remaining_sum_insured(policy(si=300000), history, "C-TEST") == Decimal(300000)
