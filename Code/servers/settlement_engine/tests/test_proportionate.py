from decimal import Decimal

from engine import Category, DeductionKind, Status, compute_settlement
from engine import calculators as calc
from factories import claim, line, policy, worked_example_lines


def test_formula_matches_the_worked_example():
    assert calc.proportionate_deduction(Decimal(74900), Decimal(15000), Decimal(21000)) == Decimal(21400)


def test_no_cut_when_room_within_limit():
    assert calc.proportionate_deduction(Decimal(74900), Decimal(15000), Decimal(15000)) == 0
    assert calc.proportionate_deduction(Decimal(74900), Decimal(0), Decimal(0)) == 0


def test_worked_example_cuts_only_associated_expenses(rules):
    r = compute_settlement(claim(worked_example_lines()), policy(), rules)
    prop = r.deduction(DeductionKind.PROPORTIONATE)
    assert prop.amount == Decimal("21400.00")
    # nursing, surgeon, anaesthetist, OT, visits
    assert set(prop.line_ids) == {"L02", "L03", "L04", "L05", "L06"}
    excluded = r.fact("F-PROP-EXCLUDED")
    assert excluded.amount == Decimal("31400.00")       # tests, MRCP, pharmacy, implants
    assert set(excluded.line_ids) == {"L07", "L08", "L09", "L10"}


def test_mid_stay_room_change_is_weighted_by_days(rules):
    lines = [
        line("L01", "Private room", 14000, qty=2, rate=7000),
        line("L02", "Semi-private room", 4000, qty=1, rate=4000),
        line("L03", "Surgeon fee", 30000),
    ]
    r = compute_settlement(claim(lines), policy(), rules)
    # eligible 2x5,000 + 4,000 = 14,000 of 18,000 charged -> cut 4/18 of 30,000
    assert r.deduction(DeductionKind.PROPORTIONATE).amount == Decimal("6666.67")


def test_gst_on_an_associated_line_is_cut_too(rules):
    lines = [line("L01", "Private room", 7000, qty=1, rate=7000),
             line("L02", "Operation theatre charges", 10000, gst=18)]
    r = compute_settlement(claim(lines), policy(), rules)
    # 11,800 x 2,000 / 7,000
    assert r.deduction(DeductionKind.PROPORTIONATE).amount == Decimal("3371.43")


def test_user_says_nursing_is_not_priced_by_room(rules):
    c = claim(worked_example_lines(), room_priced_by_category={Category.NURSING: False})
    r = compute_settlement(c, policy(), rules)
    # 74,900 - 4,500 = 70,400 x 2/7
    assert r.deduction(DeductionKind.PROPORTIONATE).amount == Decimal("20114.29")


def test_unknown_line_with_room_above_cap_asks_first(rules):
    lines = worked_example_lines() + [line("L11", "Platelet transfusion", 8500)]
    r = compute_settlement(claim(lines), policy(), rules)
    assert r.status == Status.NEEDS_INFORMATION
    assert r.payable_amount is None
    assert r.deduction(DeductionKind.PROPORTIONATE) is None
    q = r.questions[0]
    assert q.question_id == "Q-ROOM-PRICING" and q.line_ids == ("L11",)


def test_answering_the_question_settles_it(rules):
    lines = worked_example_lines() + [line("L11", "Platelet transfusion", 8500)]
    r = compute_settlement(claim(lines, room_priced_by_category={Category.BLOOD_PRODUCTS: False}), policy(), rules)
    assert r.status == Status.COMPUTED
    assert r.deduction(DeductionKind.PROPORTIONATE).amount == Decimal("21400.00")


def test_unknown_line_without_room_excess_is_only_a_warning(rules):
    lines = [line("L01", "Semi-private room", 9000, qty=2, rate=4500), line("L02", "Oxygen therapy", 2000)]
    r = compute_settlement(claim(lines), policy(si=500000), rules)
    assert r.status == Status.COMPUTED
    assert any("L02" in w for w in r.warnings)
