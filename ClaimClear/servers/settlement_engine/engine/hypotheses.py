"""Hypothesis library: the ways an insurer might have calculated a deduction.

Each hypothesis is one calculation, written as code, that produces a figure for
one kind of letter row. A few are **correct**: they return what the policy
wording requires, read from the engine's own result. The rest are **documented
wrong methods** seen in real settlements: a cut applied to every line, the
wrong sub-limit, a waiting period counted from the renewal, and so on.

The matcher runs them against the insurer's figures. A wrong hypothesis that
reproduces the insurer's figure within ₹1 identifies the insurer's method.

Rules for hypotheses:
  * Pure functions of the case (claim, policy, rules, history, engine result,
    and the letter itself for co-pay). No LLM, no I/O.
  * Reuse ``calculators.py`` so a wrong method differs from the right one in
    exactly one documented way.
  * ``description`` is plain English. The explainer may quote it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from . import calculators as calc
from .categories import service_words
from .models import (
    BillLine,
    Category,
    Claim,
    ConditionType,
    DeductionKind,
    LetterRow,
    LineView,
    PastClaim,
    Policy,
    PolicyRules,
    RowKind,
    SettlementLetter,
    SettlementResult,
)
from .money import D, ZERO, pct_of, round_paise

# Which engine deductions make up the policy-correct figure for each kind of row.
ROW_DEDUCTIONS: dict[RowKind, frozenset[DeductionKind]] = {
    RowKind.ROOM_RENT: frozenset({DeductionKind.ROOM_RENT_EXCESS}),
    RowKind.ROOM_GST: frozenset({DeductionKind.ROOM_GST_EXCESS}),
    RowKind.ICU: frozenset({DeductionKind.ICU_EXCESS}),
    RowKind.ICU_GST: frozenset({DeductionKind.ICU_GST_EXCESS}),
    RowKind.ROOM_AND_ICU: frozenset({DeductionKind.ROOM_RENT_EXCESS, DeductionKind.ICU_EXCESS}),
    RowKind.PROPORTIONATE: frozenset({DeductionKind.PROPORTIONATE}),
    RowKind.NON_PAYABLE: frozenset({DeductionKind.NON_PAYABLE}),
    RowKind.CATARACT: frozenset({DeductionKind.CATARACT_LIMIT}),
    RowKind.WAITING_PERIOD: frozenset({DeductionKind.WAITING_PERIOD}),
    RowKind.SUM_INSURED: frozenset({DeductionKind.SUM_INSURED_EXHAUSTED}),
    RowKind.DUPLICATE: frozenset({DeductionKind.DUPLICATE_LINE}),
    RowKind.COVER_WINDOW: frozenset({DeductionKind.OUTSIDE_COVER_WINDOW}),
    RowKind.AMBULANCE: frozenset({DeductionKind.AMBULANCE_LIMIT}),
    RowKind.POLICY_PERIOD: frozenset(),
    RowKind.ALREADY_PAID: frozenset({DeductionKind.ALREADY_SETTLED}),
    RowKind.UNITEMISED: frozenset(),
    RowKind.COPAY: frozenset(),
    RowKind.UNSPECIFIED: frozenset(),
}

ROW_RULE_REF: dict[RowKind, str] = {
    RowKind.ROOM_RENT: "room_rent_cap",
    RowKind.ROOM_GST: "gst_follows_charge",
    RowKind.ICU: "icu_cap",
    RowKind.ICU_GST: "gst_follows_charge",
    RowKind.ROOM_AND_ICU: "room_rent_cap",
    RowKind.PROPORTIONATE: "proportionate_deduction",
    RowKind.NON_PAYABLE: "non_payable_items",
    RowKind.CATARACT: "cataract_limit",
    RowKind.COPAY: "copay",
    RowKind.WAITING_PERIOD: "listed_illness_waiting_period",
    RowKind.SUM_INSURED: "sum_insured",
    RowKind.DUPLICATE: "expenses_actually_incurred",
    RowKind.COVER_WINDOW: "post_hospitalisation",
    RowKind.AMBULANCE: "ambulance_limit",
    RowKind.POLICY_PERIOD: "policy_period",
    RowKind.ALREADY_PAID: "expenses_actually_incurred",
    RowKind.UNITEMISED: "expenses_actually_incurred",
    RowKind.UNSPECIFIED: "",
}


# --------------------------------------------------------------------------- context


@dataclass
class CaseContext:
    """Everything a hypothesis may look at."""

    claim: Claim
    policy: Policy
    rules: PolicyRules
    history: list[PastClaim]
    result: SettlementResult
    letter: Optional[SettlementLetter] = None
    row: Optional[LetterRow] = None   # the letter row being tested (set by the matcher)
    raw: dict[str, BillLine] = field(init=False)

    def __post_init__(self) -> None:
        self.raw = {line.line_id: line for line in self.claim.lines}

    # ---- engine figures
    @property
    def si(self) -> Decimal:
        return D(self.policy.sum_insured)

    @property
    def claimed(self) -> Decimal:
        return self.result.claimed_amount

    def engine_amount(self, kinds: frozenset[DeductionKind]) -> Decimal:
        return sum((d.amount for d in self.result.deductions if d.kind in kinds), ZERO)

    def policy_amount(self, kind: RowKind) -> Decimal:
        """What the wording requires for a row of this kind."""
        if kind == RowKind.COPAY:
            return self.result.copay_amount or ZERO
        if kind == RowKind.UNITEMISED:
            return self.unitemised()
        return self.engine_amount(ROW_DEDUCTIONS[kind])

    def unitemised(self) -> Decimal:
        """What the letter's claimed amount carries beyond the bill's lines (a printed total no line supports).

        The engine starts from the lines, so this amount is never in its claimed amount; a letter that
        starts from the printed total must take it out.
        """
        if self.letter is None:
            return ZERO
        return max(ZERO, D(self.letter.claimed_amount) - self.result.claimed_amount)

    def payable_lines(self) -> list[LineView]:
        return [v for v in self.result.lines if not v.non_payable]

    def lines_of(self, *categories: Category, include_non_payable: bool = False) -> list[LineView]:
        pool = self.result.lines if include_non_payable else self.payable_lines()
        return [v for v in pool if v.category in categories]

    def room_totals(self, cap: Decimal) -> tuple[Decimal, Decimal, list[str]]:
        """``(eligible, actual, over_cap_line_ids)`` for room lines at ``cap`` a day."""
        eligible = actual = ZERO
        over = []
        for v in self.lines_of(Category.ROOM):
            line = self.raw[v.line_id]
            days, rate = D(line.qty), D(line.unit_rate)
            actual += rate * days
            eligible += min(rate, cap) * days
            if rate > cap:
                over.append(v.line_id)
        return eligible, actual, over

    def deducted_before_cataract(self) -> Decimal:
        """Claimed amount less the deductions the engine applies before the cataract limit."""
        kinds = frozenset({DeductionKind.NON_PAYABLE, DeductionKind.ROOM_RENT_EXCESS, DeductionKind.ROOM_GST_EXCESS,
                           DeductionKind.ICU_EXCESS, DeductionKind.ICU_GST_EXCESS, DeductionKind.PROPORTIONATE})
        return self.claimed - self.engine_amount(kinds)

    def insurer_base(self) -> Optional[Decimal]:
        """The insurer's own admissible amount: letter claimed amount less its deduction rows."""
        if self.letter is None:
            return None
        return self.letter.claimed_amount - sum((r.amount for r in self.letter.rows), ZERO)


@dataclass(frozen=True)
class Candidate:
    """One figure a hypothesis produces, with how it got there."""

    amount: Decimal
    detail: str
    line_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    kind: RowKind
    correct: bool
    title: str
    description: str
    compute: Callable[[CaseContext], list[Candidate]]
    question: str = ""          # asked when this ties with another hypothesis
    method_only: bool = False   # right method, insurer's base (co-pay); gives Verdict.METHOD_MATCHES

    def run(self, ctx: CaseContext) -> list[Candidate]:
        out = []
        for c in self.compute(ctx):
            out.append(Candidate(round_paise(c.amount), c.detail, c.line_ids))
        return out

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "kind": self.kind.value,
            "correct": self.correct,
            "method_only": self.method_only,
            "title": self.title,
            "description": self.description,
        }


HYPOTHESES: dict[str, Hypothesis] = {}


def hypothesis(hypothesis_id: str, kind: RowKind, title: str, description: str, *, correct: bool = False,
               question: str = "", method_only: bool = False):
    """Decorator that registers a hypothesis."""
    def wrap(fn: Callable[[CaseContext], list[Candidate]]) -> Callable[[CaseContext], list[Candidate]]:
        if hypothesis_id in HYPOTHESES:
            raise ValueError(f"duplicate hypothesis {hypothesis_id}")
        HYPOTHESES[hypothesis_id] = Hypothesis(hypothesis_id, kind, correct, title, description, fn,
                                               question, method_only)
        return fn
    return wrap


def list_hypotheses(kind: Optional[RowKind] = None) -> list[Hypothesis]:
    """All hypotheses, or those for one kind of row. Correct ones first."""
    hs = [h for h in HYPOTHESES.values() if kind is None or h.kind == kind]
    return sorted(hs, key=lambda h: (h.kind.value, not h.correct, h.hypothesis_id))


def _n(value: Decimal) -> str:
    """Short number for details: 30371.428 -> 30,371.43."""
    value = round_paise(value)
    whole, _, frac = f"{value:,.2f}".partition(".")
    return whole if frac == "00" else f"{whole}.{frac}"


def _sum(lines: list[LineView]) -> Decimal:
    return sum((v.amount + v.gst for v in lines), ZERO)


def _ids(lines: list[LineView]) -> tuple[str, ...]:
    return tuple(v.line_id for v in lines)


# Words that say what kind of row it is, not which bill line it is about.
_ROW_WORDS = frozenset({"a", "an", "and", "as", "bill", "charge", "charged", "charges", "for", "from", "in", "item",
                        "items", "listed", "non", "nonpayable", "not", "of", "on", "payable", "per", "policy", "row",
                        "the", "to", "under", "with"})


def words(text: str) -> frozenset[str]:
    """Significant words of a description, singular: 'Sterile gloves' -> {'sterile', 'glove'}."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in _ROW_WORDS:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return frozenset(out)


# The part of a row that says why, not which item: "Gauze - List III (part of procedure charges)",
# "Tonic - outside post-hospitalisation period (75 days)".
_ROW_REASON = re.compile(r"\s+[-–:]\s*(list\s+(i{1,3}|iv|v)\b|annexure|outside\b|beyond\b).*$", re.I)


def named_lines(ctx: CaseContext, pool: list[LineView]) -> list[LineView]:
    """The lines of ``pool`` that the letter row being tested names in its particulars."""
    if ctx.row is None:
        return []
    said = words(_ROW_REASON.sub("", ctx.row.particulars))
    return [v for v in pool if words(v.description) & said]


# Kinds of row that are about particular bill lines: the policy figure for such a row is the
# figure for the lines it names, when it names any.
NAMED_LINE_KINDS = frozenset({RowKind.NON_PAYABLE, RowKind.DUPLICATE, RowKind.COVER_WINDOW})


def row_policy_amount(ctx: CaseContext, kind: RowKind) -> Decimal:
    """What the wording requires for the row being tested.

    For a row about particular lines ("Crepe bandage - not payable") it is the engine's deduction on
    the lines the row names, so a row is never measured against another line's deduction. A row that
    names no line is measured against every deduction of its kind.
    """
    if kind in NAMED_LINE_KINDS and ctx.row is not None:
        named = {v.line_id for v in named_lines(ctx, list(ctx.result.lines))}
        if named:
            return sum((d.amount for d in ctx.result.deductions
                        if d.kind in ROW_DEDUCTIONS[kind] and named & set(d.line_ids)), ZERO)
    return ctx.policy_amount(kind)


# --------------------------------------------------------------------------- correct methods (one per kind)


def _policy(kind: RowKind) -> Callable[[CaseContext], list[Candidate]]:
    def compute(ctx: CaseContext) -> list[Candidate]:
        amount = ctx.policy_amount(kind)
        parts = [f"{d.description}: {d.formula}" for d in ctx.result.deductions if d.kind in ROW_DEDUCTIONS[kind]]
        if kind == RowKind.COPAY:
            f = ctx.result.fact("F-COPAY")
            parts = [f.formula] if f else []
        if kind == RowKind.UNITEMISED:
            parts = [f"letter's claimed {_n(ctx.letter.claimed_amount)} - itemised lines {_n(ctx.claimed)}"] if amount else []
            if not amount:
                return []
        return [Candidate(amount, "; ".join(parts) or "nothing to deduct under the policy")]
    return compute


_POLICY_TEXT = {
    RowKind.ROOM_RENT: ("Room rent above the policy limit", "Daily room rent above the lower of 2% of sum insured and ₹5,000, times the days."),
    RowKind.ROOM_GST: ("GST on the disallowed room rent", "GST at the room line's rate on the part of the room rent above the limit."),
    RowKind.ICU: ("ICU charges above the policy limit", "Daily ICU charges above the lower of 5% of sum insured and ₹10,000, times the days."),
    RowKind.ICU_GST: ("GST on the disallowed ICU charges", "GST at the ICU line's rate on the part above the limit."),
    RowKind.PROPORTIONATE: ("Proportionate deduction on associated expenses only",
                            "Room-linked charges (nursing, doctors' fees, OT) cut in the ratio of eligible to actual room rent. "
                            "Pharmacy, consumables, implants, diagnostics and ICU are never cut."),
    RowKind.NON_PAYABLE: ("Items on the non-payable list", "Only the items the policy lists as non-payable, with their GST."),
    RowKind.CATARACT: ("Cataract limit per eye", "The lower of 25% of sum insured and ₹40,000 per eye per policy period, less what was used earlier that period."),
    RowKind.COPAY: ("Co-pay on the policy-correct admissible amount", "5% of the amount admissible after every other deduction the policy allows."),
    RowKind.WAITING_PERIOD: ("Waiting periods counted from first inception", "Waiting periods run from the date the policy was first taken, not from the latest renewal."),
    RowKind.SUM_INSURED: ("Sum insured left this policy period", "Payments are capped at the sum insured less claims paid earlier in the same policy period."),
    RowKind.DUPLICATE: ("Charges billed twice for the same day", "A line that repeats another line's service, date and amount is paid once."),
    RowKind.COVER_WINDOW: ("Bills outside the pre/post-hospitalisation days",
                           "A bill dated more than 30 days before admission or 60 days after discharge is not paid."),
    RowKind.AMBULANCE: ("Road ambulance above its limit", "Road ambulance is paid up to ₹2,000 per hospitalisation."),
    RowKind.UNITEMISED: ("Amount the itemised lines don't support",
                         "A bill total or claimed amount higher than its lines add up to: only itemised charges are paid."),
    RowKind.ROOM_AND_ICU: ("Room rent and ICU above their limits",
                           "Room days above the room-rent limit plus ICU days above the ICU limit, each at its own cap."),
    RowKind.ALREADY_PAID: ("The same hospitalisation already settled",
                           "A claim for a hospitalisation that an earlier settled claim on the policy already paid is not paid again."),
    RowKind.POLICY_PERIOD: ("Admission inside the policy period",
                            "The claim is covered when the admission date falls inside the policy period on record."),
}

for _kind, (_title, _desc) in _POLICY_TEXT.items():
    hypothesis(f"{_kind.value}_policy", _kind, _title, _desc, correct=True)(_policy(_kind))


# --------------------------------------------------------------------------- room rent


def _room_excess(ctx: CaseContext, cap: Decimal, extra_days: int = 0) -> list[Candidate]:
    total = ZERO
    ids = []
    parts = []
    for v in ctx.lines_of(Category.ROOM):
        line = ctx.raw[v.line_id]
        days = D(line.qty) + extra_days
        excess = calc.excess_over_cap(D(line.unit_rate), days, cap)
        if excess > 0:
            total += excess
            ids.append(v.line_id)
            parts.append(f"{_n(days)} x ({_n(line.unit_rate)} - {_n(cap)})")
    return [Candidate(total, " + ".join(parts) or "no room above the cap", tuple(ids))] if total else []


@hypothesis("room_cap_pct_only", RowKind.ROOM_RENT, "Room cap at 2% of sum insured, ignoring the ₹5,000 maximum",
            "The cap is taken as the percentage of sum insured alone, without the rupee maximum.")
def _room_cap_pct_only(ctx):
    return _room_excess(ctx, pct_of(ctx.rules.room_pct_of_si, ctx.si))


@hypothesis("room_cap_max_only", RowKind.ROOM_RENT, "Room cap at ₹5,000, ignoring 2% of sum insured",
            "The cap is taken as the rupee maximum alone, without the percentage of sum insured.")
def _room_cap_max_only(ctx):
    return _room_excess(ctx, ctx.rules.room_max_inr)


@hypothesis("room_days_incl_discharge", RowKind.ROOM_RENT, "Room excess counted for one day too many",
            "The discharge day is counted as an extra room day.")
def _room_days_incl_discharge(ctx):
    return _room_excess(ctx, calc.room_cap_per_day(ctx.rules, ctx.si), extra_days=1)


@hypothesis("room_gst_on_full_room", RowKind.ROOM_GST, "GST disallowed on the whole room charge",
            "All the GST on the room line is disallowed, not just the GST on the part above the limit.")
def _room_gst_on_full_room(ctx):
    cap = calc.room_cap_per_day(ctx.rules, ctx.si)
    over = [v for v in ctx.lines_of(Category.ROOM) if D(ctx.raw[v.line_id].unit_rate) > cap and v.gst]
    return [Candidate(sum((v.gst for v in over), ZERO), f"all GST on {', '.join(_ids(over))}", _ids(over))] if over else []


# --------------------------------------------------------------------------- ICU


def _icu_excess(ctx: CaseContext, cap: Decimal) -> list[Candidate]:
    total = ZERO
    ids = []
    for v in ctx.lines_of(Category.ICU):
        line = ctx.raw[v.line_id]
        excess = calc.excess_over_cap(D(line.unit_rate), D(line.qty), cap)
        if excess > 0:
            total += excess
            ids.append(v.line_id)
    return [Candidate(total, f"ICU days above {_n(cap)} a day", tuple(ids))] if total else []


@hypothesis("icu_room_cap_used", RowKind.ICU, "ICU charges capped at the room-rent limit",
            "The lower room-rent limit is applied to ICU days instead of the ICU limit.")
def _icu_room_cap_used(ctx):
    return _icu_excess(ctx, calc.room_cap_per_day(ctx.rules, ctx.si))


@hypothesis("icu_cap_pct_only", RowKind.ICU, "ICU cap at 5% of sum insured, ignoring the ₹10,000 maximum",
            "The ICU cap is the percentage of sum insured alone.")
def _icu_cap_pct_only(ctx):
    return _icu_excess(ctx, pct_of(ctx.rules.icu_pct_of_si, ctx.si))


@hypothesis("icu_cap_max_only", RowKind.ICU, "ICU cap at ₹10,000, ignoring 5% of sum insured",
            "The ICU cap is the rupee maximum alone.")
def _icu_cap_max_only(ctx):
    return _icu_excess(ctx, ctx.rules.icu_max_inr)


@hypothesis("room_and_icu_room_cap_on_icu", RowKind.ROOM_AND_ICU, "ICU days capped at the room-rent limit",
            "Room days above the room-rent limit, plus ICU days above the room-rent limit instead of the ICU limit.")
def _room_and_icu_room_cap_on_icu(ctx):
    cap = calc.room_cap_per_day(ctx.rules, ctx.si)
    room = _room_excess(ctx, cap)
    icu = _icu_excess(ctx, cap)
    if not icu:
        return []
    total = (room[0].amount if room else ZERO) + icu[0].amount
    return [Candidate(total, f"room and ICU days above {_n(cap)} a day", (room[0].line_ids if room else ()) + icu[0].line_ids)]


# --------------------------------------------------------------------------- proportionate deduction


def _prop(ctx: CaseContext, base_lines: list[LineView], label: str) -> list[Candidate]:
    eligible, actual, over = ctx.room_totals(calc.room_cap_per_day(ctx.rules, ctx.si))
    if not over or not base_lines:
        return []
    base = _sum(base_lines)
    amount = calc.proportionate_deduction(base, eligible, actual)
    return [Candidate(amount, f"{label}: {_n(base)} x ({_n(actual)} - {_n(eligible)}) / {_n(actual)}", _ids(base_lines))]


def _linked(ctx: CaseContext) -> list[LineView]:
    return [v for v in ctx.payable_lines() if v.room_linked is True]


@hypothesis("prop_on_all_lines", RowKind.PROPORTIONATE, "Proportionate cut applied to every non-room line",
            "The ratio is applied to every charge except the room, including pharmacy, consumables, implants and "
            "diagnostics, which the IRDAI norms exclude.",
            question="Does the hospital charge different prices for medicines, tests and implants depending on the room type?")
def _prop_on_all_lines(ctx):
    lines = [v for v in ctx.payable_lines() if v.category not in (Category.ROOM, Category.ICU)]
    return _prop(ctx, lines, "every non-room line")


@hypothesis("prop_on_all_lines_incl_icu", RowKind.PROPORTIONATE, "Proportionate cut applied to every non-room line, ICU included",
            "As 'every non-room line', but ICU charges are cut too.")
def _prop_on_all_lines_incl_icu(ctx):
    lines = [v for v in ctx.payable_lines() if v.category != Category.ROOM]
    return _prop(ctx, lines, "every non-room line incl. ICU")


@hypothesis("prop_incl_non_payable", RowKind.PROPORTIONATE, "Proportionate cut applied before removing non-payable items",
            "The ratio is applied to every non-room line, including items already disallowed as non-payable.")
def _prop_incl_non_payable(ctx):
    lines = [v for v in ctx.result.lines if v.category not in (Category.ROOM, Category.ICU)]
    return _prop(ctx, lines, "every non-room line incl. non-payables")


@hypothesis("prop_incl_pharmacy", RowKind.PROPORTIONATE, "Proportionate cut also applied to pharmacy",
            "Associated expenses plus pharmacy are cut. The IRDAI norms exclude pharmacy.",
            question="Does the hospital charge different medicine prices depending on the room type?")
def _prop_incl_pharmacy(ctx):
    return _prop(ctx, _linked(ctx) + ctx.lines_of(Category.PHARMACY), "associated expenses + pharmacy")


@hypothesis("prop_incl_diagnostics", RowKind.PROPORTIONATE, "Proportionate cut also applied to diagnostics",
            "Associated expenses plus tests and scans are cut. The IRDAI norms exclude diagnostics.",
            question="Does the hospital charge different prices for tests and scans depending on the room type?")
def _prop_incl_diagnostics(ctx):
    return _prop(ctx, _linked(ctx) + ctx.lines_of(Category.DIAGNOSTICS), "associated expenses + diagnostics")


@hypothesis("prop_incl_implants", RowKind.PROPORTIONATE, "Proportionate cut also applied to implants",
            "Associated expenses plus implants and devices are cut. The IRDAI norms exclude implants.",
            question="Does the hospital charge different prices for implants depending on the room type?")
def _prop_incl_implants(ctx):
    return _prop(ctx, _linked(ctx) + ctx.lines_of(Category.IMPLANTS), "associated expenses + implants")


@hypothesis("prop_on_whole_bill", RowKind.PROPORTIONATE, "Proportionate cut applied to the whole bill",
            "The ratio is applied to the entire bill, room included, as popular explainers describe it.")
def _prop_on_whole_bill(ctx):
    return _prop(ctx, list(ctx.result.lines), "whole bill")


@hypothesis("prop_round_each_line", RowKind.PROPORTIONATE, "Proportionate cut rounded to the rupee on each line",
            "The right lines are cut, but each line's cut is rounded to whole rupees before adding up.")
def _prop_round_each_line(ctx):
    eligible, actual, over = ctx.room_totals(calc.room_cap_per_day(ctx.rules, ctx.si))
    lines = _linked(ctx)
    if not over or not lines:
        return []
    total = sum((round_paise(calc.proportionate_deduction(v.amount + v.gst, eligible, actual)).quantize(D(1))
                 for v in lines), ZERO)
    return [Candidate(total, "each associated line's cut rounded to the rupee", _ids(lines))]


# --------------------------------------------------------------------------- non-payable items


@hypothesis("non_payable_named_items", RowKind.NON_PAYABLE, "The non-payable items this row names",
            "Only the items on the non-payable list that the letter row names, with their GST. A letter may "
            "split the non-payable items over several rows.", correct=True)
def _nonpay_named_items(ctx):
    lines = named_lines(ctx, [v for v in ctx.result.lines if v.non_payable])
    if not lines:
        return []
    return [Candidate(_sum(lines), " + ".join(f"'{v.description}' {_n(v.amount + v.gst)}" for v in lines), _ids(lines))]


@hypothesis("nonpay_payable_item_listed", RowKind.NON_PAYABLE, "A payable item counted as non-payable",
            "The non-payable deduction includes one line that is not on the non-payable list.")
def _nonpay_payable_item_listed(ctx):
    base = row_policy_amount(ctx, RowKind.NON_PAYABLE)
    out = []
    for v in ctx.payable_lines():
        if v.category in (Category.ROOM, Category.ICU):
            continue
        out.append(Candidate(base + v.amount + v.gst, f"non-payables {_n(base)} + '{v.description}' {_n(v.amount + v.gst)}",
                             (v.line_id,)))
    return out


# --------------------------------------------------------------------------- duplicate charges


@hypothesis("duplicate_named_items", RowKind.DUPLICATE, "The repeated charges this row names",
            "Only the lines billed twice for the same day that the letter row names.", correct=True)
def _duplicate_named_items(ctx):
    dup_ids = {i for d in ctx.result.deductions if d.kind == DeductionKind.DUPLICATE_LINE for i in d.line_ids}
    lines = named_lines(ctx, [v for v in ctx.result.lines if v.line_id in dup_ids])
    if not lines:
        return []
    return [Candidate(_sum(lines), " + ".join(f"'{v.description}' {_n(v.amount + v.gst)}" for v in lines), _ids(lines))]


@hypothesis("duplicate_daily_repeats", RowKind.DUPLICATE, "A daily charge treated as a duplicate of the first day",
            "The same service billed on later days of the stay (daily oxygen, daily doctor's rounds) removed as if it "
            "were billed twice. A charge for another day is a new expense, not a duplicate.",
            question="Were the repeated charges for different days of the stay?")
def _duplicate_daily_repeats(ctx):
    groups: dict[frozenset[str], list[tuple]] = {}
    for v in ctx.payable_lines():
        day = ctx.raw[v.line_id].date
        if day is not None:
            groups.setdefault(service_words(v.description), []).append((day, v))
    named = set(_ids(named_lines(ctx, ctx.payable_lines())))
    out = []
    for items in groups.values():
        days = sorted({day for day, _ in items})
        if len(days) < 2 or (named and not any(v.line_id in named for _, v in items)):
            continue
        later = [v for day, v in items if day != days[0]]
        out.append(Candidate(_sum(later), f"'{items[0][1].description}' on {len(days) - 1} later days "
                                          f"({_n(_sum(later))})", _ids(later)))
    return out


# --------------------------------------------------------------------------- cataract


def _cataract_with_limit(ctx: CaseContext, per_eye: Decimal, label: str, history_all_years: bool = False) -> list[Candidate]:
    if not calc.is_cataract(ctx.claim.diagnosis, ctx.claim.procedure, *(l.description for l in ctx.claim.lines)):
        return []
    eyes = calc.eyes_treated(ctx.claim.diagnosis, ctx.claim.procedure,
                             *(l.description for l in ctx.claim.lines)) or frozenset({"right"})
    remaining = ZERO
    for eye in eyes:
        used = ZERO
        if history_all_years:
            for c in ctx.history:
                if (c.policy_no == ctx.policy.policy_no and c.status.lower() == "settled"
                        and c.claim_id != ctx.claim.claim_id and calc.is_cataract(c.diagnosis, c.procedure)):
                    e = calc.eyes_treated(c.diagnosis, c.procedure)
                    if e and eye in e:
                        used += c.settled_amount / len(e)
        else:
            used = calc.cataract_used_this_period(ctx.policy, ctx.history, eye, ctx.claim.claim_id)
        remaining += max(ZERO, per_eye - used)
    so_far = ctx.deducted_before_cataract()
    excess = max(ZERO, so_far - remaining)
    return [Candidate(excess, f"{label}: {_n(so_far)} - limit {_n(remaining)}")] if excess else []


@hypothesis("cataract_15pct_si", RowKind.CATARACT, "Cataract limit taken as 15% of sum insured",
            "The limit is taken as 15% of sum insured instead of the lower of 25% of sum insured and ₹40,000.")
def _cataract_15pct_si(ctx):
    return _cataract_with_limit(ctx, pct_of(15, ctx.si), "15% of sum insured")


@hypothesis("cataract_pct_only", RowKind.CATARACT, "Cataract limit at 25% of sum insured, ignoring ₹40,000",
            "The percentage of sum insured is used without the rupee maximum.")
def _cataract_pct_only(ctx):
    return _cataract_with_limit(ctx, pct_of(ctx.rules.cataract_pct_of_si, ctx.si), "25% of sum insured")


@hypothesis("cataract_max_only", RowKind.CATARACT, "Cataract limit at ₹40,000, ignoring 25% of sum insured",
            "The rupee maximum is used without the percentage of sum insured.")
def _cataract_max_only(ctx):
    return _cataract_with_limit(ctx, ctx.rules.cataract_max_inr, "₹40,000")


@hypothesis("cataract_mixes_policy_years", RowKind.CATARACT, "Cataract limit reduced by claims from earlier policy years",
            "Cataract claims from previous policy years are subtracted from this year's limit.")
def _cataract_mixes_policy_years(ctx):
    return _cataract_with_limit(ctx, calc.cataract_limit_per_eye(ctx.rules, ctx.si), "all policy years",
                                history_all_years=True)


@hypothesis("cataract_shared_between_eyes", RowKind.CATARACT, "Cataract limit shared between the two eyes",
            "An earlier cataract claim on the other eye is taken off this eye's limit, although the limit applies "
            "per eye per policy period.")
def _cataract_shared_between_eyes(ctx):
    if not calc.is_cataract(ctx.claim.diagnosis, ctx.claim.procedure, *(l.description for l in ctx.claim.lines)):
        return []
    eyes = calc.eyes_treated(ctx.claim.diagnosis, ctx.claim.procedure, *(l.description for l in ctx.claim.lines))
    earlier = [c for c in calc.claims_in_period(ctx.policy, ctx.history, ctx.claim.claim_id)
               if calc.is_cataract(c.diagnosis, c.procedure)]
    other_eye = [c for c in earlier if not eyes or not (calc.eyes_treated(c.diagnosis, c.procedure) or set()) & eyes]
    if not other_eye:
        return []
    per_eye = calc.cataract_limit_per_eye(ctx.rules, ctx.si)
    so_far = ctx.deducted_before_cataract()
    paid = sum((c.settled_amount for c in other_eye), ZERO)
    keep = (D(100) - ctx.rules.copay_pct) / D(100)
    out = []
    for used, label in ((paid, "paid"), (paid / keep, "admitted before co-pay")):
        left = max(ZERO, per_eye - used)
        if so_far > left:
            out.append(Candidate(so_far - left, f"{_n(so_far)} - limit {_n(per_eye)} less the other eye's "
                                                f"{_n(used)} {label} = {_n(left)}"))
    return out


# --------------------------------------------------------------------------- co-pay


@hypothesis("copay_on_insurer_base", RowKind.COPAY, "Co-pay at the right rate on the insurer's own admissible amount",
            "The co-pay method is right, but it is applied after the insurer's other deductions, so any error "
            "in those carries into the co-pay.", method_only=True)
def _copay_on_insurer_base(ctx):
    base = ctx.insurer_base()
    return [] if base is None else [Candidate(pct_of(ctx.rules.copay_pct, base),
                                              f"{ctx.rules.copay_pct}% of the insurer's admissible {_n(base)}")]


@hypothesis("copay_on_claimed", RowKind.COPAY, "Co-pay on the full bill",
            "The co-pay is worked out on the whole bill before any other deduction.")
def _copay_on_claimed(ctx):
    return [Candidate(pct_of(ctx.rules.copay_pct, ctx.claimed), f"{ctx.rules.copay_pct}% of {_n(ctx.claimed)}")]


@hypothesis("copay_twice", RowKind.COPAY, "Co-pay applied twice",
            "The co-pay is taken, then taken again on what is left.")
def _copay_twice(ctx):
    base = ctx.insurer_base()
    if base is None:
        return []
    p = ctx.rules.copay_pct / D(100)
    return [Candidate(base * (1 - (1 - p) ** 2), f"{ctx.rules.copay_pct}% twice on {_n(base)}")]


@hypothesis("copay_double_rate", RowKind.COPAY, "Co-pay at double the rate",
            "The co-pay is taken at twice the policy's rate.")
def _copay_double_rate(ctx):
    base = ctx.insurer_base()
    return [] if base is None else [Candidate(pct_of(ctx.rules.copay_pct * 2, base),
                                              f"{ctx.rules.copay_pct * 2}% of {_n(base)}")]


# --------------------------------------------------------------------------- waiting periods


def _rejects(ctx: CaseContext, start, condition: Optional[ConditionType], label: str) -> Optional[str]:
    """Why the claim fails a waiting period counted from ``start``, or ``None`` if it passes."""
    listed = condition is None and calc.looks_listed_illness(ctx.claim.diagnosis, ctx.claim.procedure)
    res = calc.waiting_period(ctx.rules, start, ctx.claim.admission, condition, listed)
    if res.served is True:
        return None
    return (f"{res.months_since_inception} full months ({res.days_since_inception} days) from {label} "
            f"{start.isoformat()} to admission, short of the {res.required} waiting period")


@hypothesis("waiting_from_renewal", RowKind.WAITING_PERIOD, "Waiting period counted from the latest renewal",
            "The waiting period is counted from the start of the current policy year instead of first inception, "
            "so years of continuous cover are ignored.")
def _waiting_from_renewal(ctx):
    if ctx.policy.period_start <= ctx.policy.first_inception:
        return []
    reason = _rejects(ctx, ctx.policy.period_start, ctx.claim.condition_type, "renewal")
    return [Candidate(ctx.claimed, reason)] if reason else []


@hypothesis("waiting_pre_existing_assumed", RowKind.WAITING_PERIOD, "Condition treated as pre-existing without it being stated",
            "The 36-month pre-existing disease waiting period is applied although no pre-existing disease was established.")
def _waiting_pre_existing_assumed(ctx):
    reason = _rejects(ctx, ctx.policy.first_inception, ConditionType.PRE_EXISTING, "first inception")
    return [Candidate(ctx.claimed, f"treated as pre-existing: {reason}")] if reason else []


# --------------------------------------------------------------------------- sum insured


@hypothesis("si_mixes_policy_years", RowKind.SUM_INSURED, "Sum insured reduced by claims from earlier policy years",
            "Claims paid in previous policy years are subtracted from this year's sum insured.")
def _si_mixes_policy_years(ctx):
    if ctx.result.admissible_amount is None or ctx.result.copay_amount is None:
        return []
    before_cap = ctx.result.admissible_amount - ctx.result.copay_amount
    used = sum((c.settled_amount for c in ctx.history
                if c.policy_no == ctx.policy.policy_no and c.status.lower() == "settled"
                and c.claim_id != ctx.claim.claim_id), ZERO)
    left = max(ZERO, ctx.si - used)
    excess = max(ZERO, before_cap - left)
    return [Candidate(excess, f"{_n(before_cap)} - sum insured left across all years {_n(left)}")] if excess else []
