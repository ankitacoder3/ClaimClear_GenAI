from decimal import Decimal

import pytest

from engine import DeductionKind, compute_settlement
from engine import calculators as calc
from factories import claim, line, policy


@pytest.mark.parametrize("si, cap", [
    (300000, 5000),    # 2% = 6,000, capped at 5,000
    (200000, 4000),    # 2% = 4,000
    (1000000, 5000),
    (250000, 5000),    # exactly at the boundary
])
def test_room_cap_per_day(rules, si, cap):
    assert calc.room_cap_per_day(rules, Decimal(si)) == Decimal(cap)


@pytest.mark.parametrize("si, cap", [(400000, 10000), (100000, 5000), (200000, 10000)])
def test_icu_cap_per_day(rules, si, cap):
    assert calc.icu_cap_per_day(rules, Decimal(si)) == Decimal(cap)


@pytest.mark.parametrize("rate, days, cap, excess", [
    (7000, 3, 5000, 6000),
    (5000, 3, 5000, 0),    # exactly at the cap
    (5001, 2, 5000, 2),    # one rupee over
    (4500, 3, 5000, 0),    # under
])
def test_excess_over_cap(rate, days, cap, excess):
    assert calc.excess_over_cap(Decimal(rate), Decimal(days), Decimal(cap)) == Decimal(excess)


def test_room_gst_on_excess_follows_the_room(rules):
    r = compute_settlement(claim([line("L01", "Private room", 21000, qty=3, rate=7000, gst=5),
                                  line("L02", "Pharmacy - inpatient medicines", 1000)]),
                           policy(), rules)
    assert r.deduction(DeductionKind.ROOM_RENT_EXCESS).amount == Decimal("6000.00")
    assert r.deduction(DeductionKind.ROOM_GST_EXCESS).amount == Decimal("300.00")


def test_room_under_cap_has_no_room_deduction(rules):
    r = compute_settlement(claim([line("L01", "Semi-private room", 13500, qty=3, rate=4500)]),
                           policy(si=500000), rules)
    assert r.deduction(DeductionKind.ROOM_RENT_EXCESS) is None
    assert r.deduction(DeductionKind.PROPORTIONATE) is None


def test_icu_above_cap(rules):
    r = compute_settlement(claim([line("L01", "ICU charges", 24000, qty=2, rate=12000),
                                  line("L02", "Nursing charges", 2000)]),
                           policy(si=400000), rules)
    assert r.deduction(DeductionKind.ICU_EXCESS).amount == Decimal("4000.00")
    # an ICU excess never triggers the proportionate deduction
    assert r.deduction(DeductionKind.PROPORTIONATE) is None


def test_zero_night_day_care_has_no_room_line(rules):
    r = compute_settlement(claim([line("L01", "OT and day-care bed charges", 2500),
                                  line("L02", "Ophthalmologist consultation", 800)],
                                 admission="2026-02-06", discharge="2026-02-06"),
                           policy(si=200000), rules)
    assert r.deductions == []
    assert r.payable_amount == Decimal("3135.00")   # 3,300 less 5% co-pay
