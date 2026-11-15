from decimal import Decimal

from engine import DeductionKind, compute_settlement
from factories import claim, line, policy


def test_flag_from_the_bill_is_used(rules):
    r = compute_settlement(claim([line("L01", "Surgeon fee", 10000),
                                  line("L02", "Consumables - gloves, masks, syringes, caps", 3360, non_payable=True)]),
                           policy(si=500000), rules)
    d = r.deduction(DeductionKind.NON_PAYABLE)
    assert d.amount == Decimal("3360.00") and d.line_ids == ("L02",)
    assert r.lines[1].non_payable_source == "input"


def test_keyword_used_when_the_bill_says_nothing(rules):
    r = compute_settlement(claim([line("L01", "Surgeon fee", 10000), line("L02", "Sterile gloves", 500)]),
                           policy(si=500000), rules)
    assert r.deduction(DeductionKind.NON_PAYABLE).amount == Decimal("500.00")
    assert r.lines[1].non_payable_source == "keyword"


def test_explicit_false_beats_the_keyword(rules):
    r = compute_settlement(claim([line("L01", "Sterile gloves", 500, non_payable=False)]), policy(si=500000), rules)
    assert r.deduction(DeductionKind.NON_PAYABLE) is None


def test_gst_on_a_non_payable_line_is_deducted_with_it(rules):
    r = compute_settlement(claim([line("L01", "Admission kit", 1000, gst=12, category=None)]), policy(si=500000), rules)
    assert r.deduction(DeductionKind.NON_PAYABLE).amount == Decimal("1120.00")


def test_non_payable_line_is_not_in_the_proportionate_base(rules):
    lines = [line("L01", "Private room", 7000, qty=1, rate=7000),
             line("L02", "Nursing charges", 7000, non_payable=True)]
    r = compute_settlement(claim(lines), policy(), rules)
    assert r.fact("F-PROP-LINKED").amount == Decimal("0.00")
    assert r.deduction(DeductionKind.PROPORTIONATE) is None   # a ₹0 cut is not listed
