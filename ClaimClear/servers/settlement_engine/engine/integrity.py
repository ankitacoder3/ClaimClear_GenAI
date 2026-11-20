"""Document integrity: definite inconsistencies on the bill itself, found by plain rules.

The engine never decides that a claim is fraudulent. These checks find facts a reader can see on the bill that
cannot all be true at once, and report them as ``integrity`` facts. The matcher uses only the **definite** ones,
and only to test a **rejection** the insurer already made: a "not genuine" rejection, or a waiting-period rejection
whose bill header dates disagree with the hospital's own line dates. A settlement is never reduced because of them.

=============================  ===========================================================  ==========
Code                           What is checked                                              Definite
=============================  ===========================================================  ==========
discharge_before_admission     the discharge date is earlier than the admission date        yes
room_days_exceed_stay          room + ICU days billed exceed the nights of the stay + 1     yes
inpatient_lines_outside_stay   every dated room / ICU / nursing / theatre / surgeon line    yes
                               falls outside the admission-discharge dates on the bill
                               (the hospital's lines and the header describe another stay)
some_inpatient_lines_outside   only some of them do (a typing slip is possible)             no
gstin_malformed                the hospital's GSTIN is not 15 characters in the official    yes
                               pattern (2 digits, PAN, entity code, Z, check character)
split_invoices                 one stay is billed on two or more invoice numbers; the       no
                               claim adds them up, and the split is reported because it
                               can keep each invoice under an insurer's approval limit
=============================  ===========================================================  ==========

The GSTIN check is structural only. The state code and check character are not tested: the synthetic dataset's
genuine bills use placeholder GSTINs (state code 00, wrong check character), so testing them would flag every bill.
Standard library only, like the rest of the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from .models import Category, Claim, LineView

INPATIENT = frozenset({Category.ROOM, Category.ICU, Category.NURSING, Category.OT, Category.PROFESSIONAL_FEES})
STAY_CATEGORIES = frozenset({Category.ROOM, Category.ICU})
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
NO_VALUE = frozenset({"", "-", "--", "na", "n/a", "nil", "none"})


@dataclass(frozen=True)
class Finding:
    code: str
    text: str
    definite: bool = True
    line_ids: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)
    heading: str = "The bill is inconsistent"     # how the fact and warning begin


def _d(day: date) -> str:
    return day.strftime("%d-%b-%Y")


def check(claim: Claim, lines: Iterable[LineView]) -> list[Finding]:
    """Every inconsistency on the bill, definite ones first."""
    lines = list(lines)
    raw = {line.line_id: line for line in claim.lines}
    out: list[Finding] = []
    adm, dis = claim.admission, claim.discharge

    if adm and dis and dis < adm:
        out.append(Finding("discharge_before_admission",
                           f"the bill's discharge date ({_d(dis)}) is before its admission date ({_d(adm)})",
                           inputs={"admission": adm.isoformat(), "discharge": dis.isoformat()}))

    if adm and dis and dis >= adm:
        nights = (dis - adm).days
        stay_lines = [v for v in lines if v.category in STAY_CATEGORIES]
        billed = sum((Decimal(raw[v.line_id].qty) for v in stay_lines), Decimal(0))
        if stay_lines and billed > nights + 1:
            out.append(Finding("room_days_exceed_stay",
                               f"the bill charges {billed.normalize():f} room and ICU days for a {nights}-night stay "
                               f"({_d(adm)} to {_d(dis)})",
                               line_ids=tuple(v.line_id for v in stay_lines),
                               inputs={"days_billed": str(billed), "nights": nights}))

        dated = [(v, raw[v.line_id].date) for v in lines if v.category in INPATIENT and raw[v.line_id].date]
        outside = [(v, d) for v, d in dated if d < adm or d > dis]
        if len(dated) >= 2 and len(outside) == len(dated):
            first, last = min(d for _, d in dated), max(d for _, d in dated)
            out.append(Finding("inpatient_lines_outside_stay",
                               f"the bill's header gives the stay as {_d(adm)} to {_d(dis)}, but all its room, "
                               f"nursing, surgeon and theatre lines are dated {_d(first)} to {_d(last)}",
                               line_ids=tuple(v.line_id for v, _ in dated),
                               inputs={"line_admission": first.isoformat(), "line_discharge": last.isoformat()}))
        elif outside:
            out.append(Finding("some_inpatient_lines_outside",
                               f"{len(outside)} inpatient line(s) are dated outside the stay {_d(adm)} to {_d(dis)}",
                               definite=False, line_ids=tuple(v.line_id for v, _ in outside)))

    gstin = re.sub(r"\s+", "", claim.hospital_gstin or "").upper()
    if gstin.lower() not in NO_VALUE and not GSTIN.match(gstin):
        out.append(Finding("gstin_malformed",
                           f"the hospital's GSTIN on the bill ({gstin}, {len(gstin)} characters) is not in the "
                           "15-character format every registered business has",
                           inputs={"gstin": gstin}))

    numbers = list(dict.fromkeys(n.strip() for n in claim.bill_numbers if n and n.strip()))
    if len(numbers) > 1:
        from .engine import _inr            # at call time: engine.py imports this module
        total = sum((Decimal(line.amount) for line in claim.lines), Decimal(0)) - Decimal(claim.discount or 0)
        stay = f" ({_d(adm)} to {_d(dis)})" if adm and dis else ""
        out.append(Finding("split_invoices",
                           f"one hospital stay{stay} is billed on {len(numbers)} separate invoices "
                           f"({', '.join(numbers)}); ClaimClear adds them up ({_inr(total)} in all). A stay split "
                           "across invoices can keep each one under an insurer's approval limit, so the insurer may "
                           "review the claim as one bill",
                           definite=False, heading="Check the bill",
                           inputs={"bill_numbers": numbers, "combined_total": str(total)}))
    return sorted(out, key=lambda f: not f.definite)


def line_dated_stay(findings: Iterable[Finding]) -> Optional[tuple[date, date]]:
    """The stay the hospital's own lines describe, when they all disagree with the header."""
    for f in findings:
        if f.code == "inpatient_lines_outside_stay":
            return date.fromisoformat(f.inputs["line_admission"]), date.fromisoformat(f.inputs["line_discharge"])
    return None
