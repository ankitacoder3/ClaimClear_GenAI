"""Typed inputs and outputs of the settlement engine.

These shapes are the contract with Member 3's agents and with the
``settlement-engine`` MCP server. Change them only together with ``CaseState``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from .money import D, round_paise


# --------------------------------------------------------------------------- enums


class Category(str, Enum):
    """What kind of charge a bill line is. Drives the proportionate deduction."""

    ROOM = "room"
    ICU = "icu"
    NURSING = "nursing"
    PROFESSIONAL_FEES = "professional_fees"
    OT = "operation_theatre"
    DIAGNOSTICS = "diagnostics"
    PHARMACY = "pharmacy"
    CONSUMABLES = "consumables"
    IMPLANTS = "implants"
    BLOOD_PRODUCTS = "blood_products"
    PACKAGE = "package"
    AMBULANCE = "ambulance"
    UNKNOWN = "unknown"


class ConditionType(str, Enum):
    """How the waiting-period rules classify the treated condition."""

    ACCIDENT = "accident"                    # no waiting period
    ILLNESS = "illness"                      # only the initial 30 days
    LISTED_ILLNESS_SHORT = "listed_illness_short"  # first value in listed_illness_waiting_months
    LISTED_ILLNESS_LONG = "listed_illness_long"    # second value in listed_illness_waiting_months
    PRE_EXISTING = "pre_existing"


class DeductionKind(str, Enum):
    ROOM_RENT_EXCESS = "room_rent_excess"
    ROOM_GST_EXCESS = "room_gst_excess"
    ICU_EXCESS = "icu_excess"
    ICU_GST_EXCESS = "icu_gst_excess"
    PROPORTIONATE = "proportionate_deduction"
    NON_PAYABLE = "non_payable"
    CATARACT_LIMIT = "cataract_limit"
    WAITING_PERIOD = "waiting_period"
    SUM_INSURED_EXHAUSTED = "sum_insured_exhausted"
    DUPLICATE_LINE = "duplicate_line"          # the same charge billed twice on the same day
    OUTSIDE_COVER_WINDOW = "outside_cover_window"  # a bill dated outside the pre/post-hospitalisation days
    AMBULANCE_LIMIT = "ambulance_limit"        # road ambulance above its limit per hospitalisation
    ALREADY_SETTLED = "already_settled"        # the same hospitalisation was settled under an earlier claim


class Status(str, Enum):
    COMPUTED = "computed"                    # every figure is known
    NEEDS_INFORMATION = "needs_information"  # ask the user before giving a payable figure
    NOT_ADMISSIBLE = "not_admissible"        # the wording excludes the whole claim


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class PolicyRules:
    """Numeric limits from the policy wording (see ``rules.py``)."""

    room_pct_of_si: Decimal
    room_max_inr: Decimal
    icu_pct_of_si: Decimal
    icu_max_inr: Decimal
    cataract_pct_of_si: Decimal
    cataract_max_inr: Decimal
    copay_pct: Decimal
    initial_waiting_days: int
    listed_illness_waiting_months: tuple[int, ...]
    pre_existing_waiting_months: int
    pre_hospitalisation_days: int = 30
    post_hospitalisation_days: int = 60
    ambulance_max_inr: Decimal = D(2000)   # road ambulance, per hospitalisation


@dataclass(frozen=True)
class Policy:
    policy_no: str
    sum_insured: Decimal
    period_start: date
    period_end: date
    first_inception: date
    holder: str = ""
    insurer: str = ""
    product: str = ""
    wording_uin: str = ""         # selects the wording's limits (policy rules); "" = standard limits
    wording_source: str = ""      # "catalogue" or "uploaded"


@dataclass(frozen=True)
class BillLine:
    """One line of the itemised hospital bill.

    ``amount`` is the printed line amount before GST. ``category`` and
    ``non_payable`` may be left as ``None``; the engine then works them out from
    the description and records how (see ``LineView.category_source``).
    """

    line_id: str
    description: str
    amount: Decimal
    qty: Decimal = D(1)
    rate: Optional[Decimal] = None
    gst_pct: Decimal = D(0)
    non_payable: Optional[bool] = None
    category: Optional[Category] = None
    date: Optional[date] = None

    @property
    def gst(self) -> Decimal:
        return self.amount * self.gst_pct / D(100)

    @property
    def unit_rate(self) -> Decimal:
        if self.rate is not None:
            return self.rate
        return self.amount / self.qty if self.qty else self.amount


@dataclass(frozen=True)
class Claim:
    """The reimbursement claim as billed by the hospital.

    ``room_priced_by_category`` lets the user (or the agent, after asking) say
    whether the hospital prices a category differently by room type. It
    overrides the default in ``categories.ROOM_LINKED``.
    """

    claim_id: str
    policy_no: str
    admission: Optional[date]   # None: the bill gives no admission date (pharmacy, post-hospitalisation)
    discharge: Optional[date]
    lines: tuple[BillLine, ...]
    diagnosis: str = ""
    procedure: str = ""
    discount: Decimal = D(0)
    printed_total: Optional[Decimal] = None
    condition_type: Optional[ConditionType] = None
    room_priced_by_category: dict[Category, bool] = field(default_factory=dict)
    hospital_gstin: str = ""    # as printed on the bill; only its format is checked (engine/integrity.py)


@dataclass(frozen=True)
class PastClaim:
    """An earlier claim on the same policy, from claim history."""

    claim_id: str
    policy_no: str
    admission: date
    status: str
    settled_amount: Decimal
    diagnosis: str = ""
    procedure: str = ""


# --------------------------------------------------------------------------- outputs


@dataclass
class Fact:
    """One checked figure or finding. Explanations and letters may cite only facts.

    ``fact_id`` is stable for the same input, so the critic can re-run the
    engine and compare by ID.
    """

    fact_id: str
    kind: str
    text: str
    amount: Optional[Decimal] = None
    formula: str = ""
    rule_ref: str = ""
    line_ids: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind,
            "text": self.text,
            "amount": _num(self.amount),
            "formula": self.formula,
            "rule_ref": self.rule_ref,
            "line_ids": list(self.line_ids),
            "inputs": {k: _jsonable(v) for k, v in self.inputs.items()},
        }


@dataclass
class Deduction:
    """A deduction the policy wording requires."""

    deduction_id: str
    kind: DeductionKind
    amount: Decimal
    description: str
    formula: str
    rule_ref: str
    line_ids: tuple[str, ...] = ()
    fact_id: str = ""

    def to_dict(self) -> dict:
        return {
            "deduction_id": self.deduction_id,
            "kind": self.kind.value,
            "amount": _num(self.amount),
            "description": self.description,
            "formula": self.formula,
            "rule_ref": self.rule_ref,
            "line_ids": list(self.line_ids),
            "fact_id": self.fact_id,
        }


@dataclass
class Question:
    """Something the engine will not guess. The agent asks the user."""

    question_id: str
    text: str
    reason: str
    line_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "reason": self.reason,
            "line_ids": list(self.line_ids),
        }


@dataclass
class LineView:
    """How the engine read each bill line."""

    line_id: str
    description: str
    amount: Decimal
    gst: Decimal
    category: Category
    category_source: str          # "input", "keyword" or "unknown"
    non_payable: bool
    non_payable_source: str       # "input", "keyword" or "default"
    room_linked: Optional[bool]   # True, False, or None when unknown

    def to_dict(self) -> dict:
        return {
            "line_id": self.line_id,
            "description": self.description,
            "amount": _num(self.amount),
            "gst": _num(self.gst),
            "category": self.category.value,
            "category_source": self.category_source,
            "non_payable": self.non_payable,
            "non_payable_source": self.non_payable_source,
            "room_linked": self.room_linked,
        }


@dataclass
class SettlementResult:
    """What the policy wording says should be paid on this claim."""

    claim_id: str
    status: Status
    claimed_amount: Decimal
    deductions: list[Deduction]
    admissible_amount: Optional[Decimal]
    copay_amount: Optional[Decimal]
    payable_amount: Optional[Decimal]
    facts: list[Fact]
    questions: list[Question]
    lines: list[LineView]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_deductions(self) -> Decimal:
        return round_paise(sum((d.amount for d in self.deductions), D(0)))

    def deduction(self, kind: DeductionKind) -> Optional[Deduction]:
        """The first deduction of ``kind``, or ``None``."""
        return next((d for d in self.deductions if d.kind == kind), None)

    def fact(self, fact_id: str) -> Optional[Fact]:
        return next((f for f in self.facts if f.fact_id == fact_id), None)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "claimed_amount": _num(self.claimed_amount),
            "deductions": [d.to_dict() for d in self.deductions],
            "total_deductions": _num(self.total_deductions),
            "admissible_amount": _num(self.admissible_amount),
            "copay_amount": _num(self.copay_amount),
            "payable_amount": _num(self.payable_amount),
            "facts": [f.to_dict() for f in self.facts],
            "questions": [q.to_dict() for q in self.questions],
            "lines": [line.to_dict() for line in self.lines],
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------- insurer letter (matcher input)


class RowKind(str, Enum):
    """What a row of the insurer's letter is about. Decides which hypotheses are tested."""

    ROOM_RENT = "room_rent"
    ROOM_GST = "room_gst"
    ICU = "icu"
    ICU_GST = "icu_gst"
    ROOM_AND_ICU = "room_and_icu"    # "Room / ICU rent above eligible limit": both caps on one row
    PROPORTIONATE = "proportionate"
    NON_PAYABLE = "non_payable"
    CATARACT = "cataract"
    COPAY = "copay"
    WAITING_PERIOD = "waiting_period"
    SUM_INSURED = "sum_insured"
    DUPLICATE = "duplicate"          # "billed twice", "duplicate entries"
    COVER_WINDOW = "cover_window"    # "outside post-hospitalisation period"
    AMBULANCE = "ambulance"          # "ambulance charges above limit"
    POLICY_PERIOD = "policy_period"  # a rejection: "admission outside the policy period"
    ALREADY_PAID = "already_paid"    # a rejection: "already settled under claim ..."
    UNITEMISED = "unitemised"        # "amount not supported by the itemised charges"
    NOT_GENUINE = "not_genuine"      # a rejection: "not genuine", "fraud", "services not provided", "not registered"
    UNSPECIFIED = "unspecified"      # "Other deductions", "as per policy terms"


class Verdict(str, Enum):
    MATCHES_POLICY = "matches_policy"                # the amount is what the wording requires
    DOES_NOT_MATCH_POLICY = "does_not_match_policy"  # a known wrong method reproduces it, or it differs from the wording
    NOT_VERIFIABLE = "not_verifiable"                # no tested calculation reproduces it, or information is missing
    METHOD_MATCHES = "method_matches"                # co-pay: right method, applied to a base that carries another row's error


@dataclass(frozen=True)
class LetterRow:
    """One deduction row on the insurer's settlement letter.

    ``kind`` may be left ``None``; the matcher then classifies the row from
    ``particulars`` (see ``matcher.classify_row``).
    """

    row_id: str
    particulars: str
    amount: Decimal
    reason: str = ""
    kind: Optional[RowKind] = None


@dataclass(frozen=True)
class SettlementLetter:
    """The insurer's decision, as the document reader extracted it."""

    letter_id: str
    letter_type: str                     # "settlement" or "rejection"
    claimed_amount: Decimal
    rows: tuple[LetterRow, ...]
    paid_amount: Decimal
    copay_amount: Optional[Decimal] = None
    rejection_reason: str = ""


# --------------------------------------------------------------------------- matcher output


@dataclass
class HypothesisMatch:
    """A hypothesis whose figure is within ₹1 of the insurer's."""

    hypothesis_id: str
    correct: bool
    title: str
    amount: Decimal
    detail: str
    line_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "correct": self.correct,
            "title": self.title,
            "amount": _num(self.amount),
            "detail": self.detail,
            "line_ids": list(self.line_ids),
        }


@dataclass
class RowAudit:
    """The verdict on one letter row."""

    row_id: str
    particulars: str
    kind: RowKind
    kind_source: str                  # "input" or "keyword"
    insurer_amount: Decimal
    policy_amount: Optional[Decimal]  # what the wording requires for this row; None if unknown
    difference: Optional[Decimal]     # insurer - policy; positive = insurer deducted more
    verdict: Verdict
    method: Optional[str]             # hypothesis_id that identifies the insurer's method
    explanation: str
    matches: list[HypothesisMatch]
    tested: list[str]
    exhaustive: bool                  # every applicable hypothesis was tested
    rule_ref: str = ""
    policy_fact_ids: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def over_deducted(self) -> bool:
        return self.difference is not None and self.difference > 1

    def to_dict(self) -> dict:
        return {
            "row_id": self.row_id,
            "particulars": self.particulars,
            "kind": self.kind.value,
            "kind_source": self.kind_source,
            "insurer_amount": _num(self.insurer_amount),
            "policy_amount": _num(self.policy_amount),
            "difference": _num(self.difference),
            "verdict": self.verdict.value,
            "method": self.method,
            "explanation": self.explanation,
            "matches": [m.to_dict() for m in self.matches],
            "tested": list(self.tested),
            "exhaustive": self.exhaustive,
            "rule_ref": self.rule_ref,
            "policy_fact_ids": list(self.policy_fact_ids),
            "questions": [q.to_dict() for q in self.questions],
        }


@dataclass
class LetterAudit:
    """Every row's verdict, plus the rupee summary for the whole letter."""

    letter_id: str
    settlement: SettlementResult
    rows: list[RowAudit]
    policy_payable: Optional[Decimal]
    insurer_paid: Decimal
    gap: Optional[Decimal]                    # policy_payable - insurer_paid
    unverified_amount: Optional[Decimal]      # after co-pay
    disputable_amount: Optional[Decimal]      # after co-pay; never negative
    overpaid_amount: Optional[Decimal]        # insurer paid more than the wording requires
    letter_arithmetic_gap: Decimal            # claimed - rows - co-pay - paid, as printed
    policy_deductions_not_on_letter: list[str]
    questions: list[Question]
    warnings: list[str] = field(default_factory=list)

    def row(self, row_id: str) -> Optional[RowAudit]:
        return next((r for r in self.rows if r.row_id == row_id), None)

    def to_dict(self) -> dict:
        return {
            "letter_id": self.letter_id,
            "rows": [r.to_dict() for r in self.rows],
            "policy_payable": _num(self.policy_payable),
            "insurer_paid": _num(self.insurer_paid),
            "gap": _num(self.gap),
            "unverified_amount": _num(self.unverified_amount),
            "disputable_amount": _num(self.disputable_amount),
            "overpaid_amount": _num(self.overpaid_amount),
            "letter_arithmetic_gap": _num(self.letter_arithmetic_gap),
            "policy_deductions_not_on_letter": list(self.policy_deductions_not_on_letter),
            "questions": [q.to_dict() for q in self.questions],
            "warnings": list(self.warnings),
            "settlement": self.settlement.to_dict(),
        }


# --------------------------------------------------------------------------- JSON helpers


def _num(value: Optional[Decimal]) -> Optional[float]:
    """Rupee amount for JSON: rounded to paise, as a number."""
    return None if value is None else float(round_paise(value))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value
