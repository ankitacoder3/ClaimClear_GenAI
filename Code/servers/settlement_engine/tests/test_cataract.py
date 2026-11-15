from decimal import Decimal

from engine import DeductionKind, Status, compute_settlement
from engine import calculators as calc
from factories import claim, line, past, policy

CATARACT_POLICY = dict(start="2025-10-01", end="2026-09-30", inception="2021-10-01")


def cataract_claim(amount, eye="right", **kw):
    desc = f"Phacoemulsification package - {eye} eye" if eye else "Phacoemulsification package"
    return claim([line("L01", desc, amount)], admission="2026-02-06", discharge="2026-02-06",
                 diagnosis=f"Senile cataract, {eye} eye" if eye else "Senile cataract", **kw)


def test_limit_is_lower_of_pct_and_max(rules):
    assert calc.cataract_limit_per_eye(rules, Decimal(200000)) == Decimal(40000)   # 25% = 50,000
    assert calc.cataract_limit_per_eye(rules, Decimal(100000)) == Decimal(25000)   # 25% = 25,000


def test_eyes_treated():
    assert calc.eyes_treated("Senile cataract, right eye") == {"right"}
    assert calc.eyes_treated("Bilateral cataract") == {"right", "left"}
    assert calc.eyes_treated("Senile cataract") is None


def test_under_the_limit_no_deduction(rules):
    r = compute_settlement(cataract_claim(38500), policy(si=200000, **CATARACT_POLICY), rules)
    assert r.deduction(DeductionKind.CATARACT_LIMIT) is None
    assert r.payable_amount == Decimal("36575.00")


def test_over_the_limit(rules):
    r = compute_settlement(cataract_claim(38500), policy(si=100000, **CATARACT_POLICY), rules)
    assert r.deduction(DeductionKind.CATARACT_LIMIT).amount == Decimal("13500.00")
    assert r.admissible_amount == Decimal("25000.00")


def test_earlier_claim_same_eye_same_period_uses_the_limit(rules):
    history = [past("H1", "2025-12-01", 30000, diagnosis="Cataract, right eye")]
    r = compute_settlement(cataract_claim(20000), policy(si=200000, **CATARACT_POLICY), rules, history)
    assert r.fact("F-CATARACT-REMAINING").amount == Decimal("10000.00")
    assert r.deduction(DeductionKind.CATARACT_LIMIT).amount == Decimal("10000.00")


def test_earlier_claim_other_eye_does_not(rules):
    history = [past("H1", "2025-12-01", 30000, diagnosis="Cataract, left eye")]
    r = compute_settlement(cataract_claim(20000), policy(si=200000, **CATARACT_POLICY), rules, history)
    assert r.deduction(DeductionKind.CATARACT_LIMIT) is None


def test_earlier_claim_in_a_previous_policy_year_does_not(rules):
    history = [past("H1", "2025-03-01", 30000, diagnosis="Cataract, right eye")]
    r = compute_settlement(cataract_claim(20000), policy(si=200000, **CATARACT_POLICY), rules, history)
    assert r.deduction(DeductionKind.CATARACT_LIMIT) is None


def test_both_eyes_get_two_limits(rules):
    r = compute_settlement(cataract_claim(70000, eye="both"), policy(si=200000, **CATARACT_POLICY), rules)
    assert r.fact("F-CATARACT-REMAINING").amount == Decimal("80000.00")
    assert r.deduction(DeductionKind.CATARACT_LIMIT) is None


def test_eye_unknown_but_under_one_eye_limit_is_fine(rules):
    r = compute_settlement(cataract_claim(30000, eye=None), policy(si=200000, **CATARACT_POLICY), rules)
    assert r.status == Status.COMPUTED


def test_eye_unknown_and_over_one_eye_limit_asks(rules):
    r = compute_settlement(cataract_claim(60000, eye=None), policy(si=200000, **CATARACT_POLICY), rules)
    assert r.status == Status.NEEDS_INFORMATION
    assert r.questions[0].question_id == "Q-EYE"
