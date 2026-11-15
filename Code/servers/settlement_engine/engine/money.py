"""Money and date helpers.

All rupee arithmetic in the engine uses ``Decimal``, never ``float``. Amounts are
rounded to paise (two decimals, half-up) only when a figure is reported, the way
a settlement letter shows it.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
PAISE = Decimal("0.01")
HUNDRED = Decimal("100")


def D(value) -> Decimal:
    """Convert an int, float, str or Decimal to Decimal without float noise.

    Floats go through ``str`` first, so ``D(0.1)`` is ``Decimal("0.1")``, not
    ``Decimal("0.1000000000000000055511151231257827")``.
    """
    if isinstance(value, Decimal):
        return value
    if value is None:
        raise ValueError("amount is missing")
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_paise(value: Decimal) -> Decimal:
    """Round to two decimals, half-up (₹4,583.9285 -> ₹4,583.93)."""
    return D(value).quantize(PAISE, rounding=ROUND_HALF_UP)


def pct_of(pct, base) -> Decimal:
    """``pct`` per cent of ``base``, unrounded."""
    return D(base) * D(pct) / HUNDRED


def to_date(value) -> date:
    """Accept a ``date`` or an ISO ``YYYY-MM-DD`` string."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def add_months(start: date, months: int) -> date:
    """Calendar-month addition, clamping to the month's last day.

    ``add_months(date(2022, 1, 31), 1)`` is 28 Feb 2022.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_completed(start: date, end: date) -> int:
    """Whole calendar months from ``start`` up to and including ``end``."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, months) > end:
        months -= 1
    return months
