from datetime import date
from decimal import Decimal

import pytest

from engine.money import D, add_months, months_completed, pct_of, round_paise


def test_float_goes_through_str():
    assert D(0.1) == Decimal("0.1")
    assert D(95617.5) == Decimal("95617.5")


def test_missing_amount_is_an_error():
    with pytest.raises(ValueError):
        D(None)


@pytest.mark.parametrize("raw, expected", [
    ("4583.9285", "4583.93"),   # SET-01 insurer co-pay
    ("30371.428571", "30371.43"),
    ("0.005", "0.01"),          # half-up, not banker's rounding
    ("0.004", "0.00"),
    ("5032.5", "5032.50"),
])
def test_round_paise_half_up(raw, expected):
    assert round_paise(Decimal(raw)) == Decimal(expected)


def test_pct_of():
    assert pct_of(2, 300000) == Decimal("6000")
    assert pct_of(5, Decimal("99900")) == Decimal("4995")


@pytest.mark.parametrize("start, months, expected", [
    (date(2022, 2, 1), 24, date(2024, 2, 1)),
    (date(2022, 1, 31), 1, date(2022, 2, 28)),   # clamps to month end
    (date(2023, 12, 15), 3, date(2024, 3, 15)),  # crosses a year
])
def test_add_months(start, months, expected):
    assert add_months(start, months) == expected


@pytest.mark.parametrize("start, end, expected", [
    (date(2022, 2, 1), date(2024, 2, 1), 24),
    (date(2022, 2, 1), date(2024, 1, 31), 23),
    (date(2022, 2, 1), date(2026, 3, 25), 49),   # SET-05
    (date(2026, 2, 1), date(2026, 1, 1), 0),     # end before start
])
def test_months_completed(start, end, expected):
    assert months_completed(start, end) == expected
