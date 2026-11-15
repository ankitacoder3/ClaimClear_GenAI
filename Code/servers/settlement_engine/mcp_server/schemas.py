"""Typed inputs and outputs of the settlement-engine MCP tools (pydantic).

These models are the published contract: the JSON schemas the agents see come
from them, and ``tests/snapshots/settlement_engine_tools.json`` pins them so a
change on either side fails CI. Field names and meanings mirror the engine's
dataclasses (``engine/models.py``) and their ``to_dict()`` output.

Inputs are bounded (string lengths, list sizes, non-negative amounts) so a
malformed or hostile document can't push unbounded data through a tool.
Policy limits (room cap, co-pay, waiting periods...) are deliberately NOT an
input: the server loads them from its own configuration, so nothing extracted
from an uploaded document can change the rules.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.models import Category, ConditionType, DeductionKind, RowKind, Status, Verdict

Money = Decimal  # accepts a JSON number or a numeric string


def _id(description: str = ""):
    """An identifier field: 1-64 characters of letters, digits and _ . / -"""
    return Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_./\-]+$", description=description or None)


SHORT_TEXT = 500
LONG_TEXT = 2000


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# =========================================================================== inputs


class BillLineIn(_In):
    """One line of the itemised hospital bill."""

    line_id: str = _id()
    description: str = Field(min_length=1, max_length=SHORT_TEXT)
    amount: Money = Field(ge=0, description="Printed line amount before GST, in rupees.")
    qty: Money = Field(default=Decimal(1), gt=0, description="Quantity, e.g. room days.")
    rate: Optional[Money] = Field(default=None, ge=0, description="Rate per unit, e.g. room rent per day.")
    gst_pct: Money = Field(default=Decimal(0), ge=0, le=100)
    non_payable: Optional[bool] = Field(
        default=None, description="As extracted from the bill. Leave null to let the engine decide.")
    category: Optional[Category] = Field(
        default=None, description="Leave null to let the engine categorise the description.")
    date: Optional[dt.date] = None


class ClaimIn(_In):
    """The reimbursement claim as billed by the hospital."""

    claim_id: str = _id()
    policy_no: str = _id()
    admission: Optional[dt.date] = Field(
        default=None, description="Null when the bill gives no admission date (pharmacy or post-hospitalisation bill): the engine asks Q-ADMISSION.")
    discharge: Optional[dt.date] = None
    lines: list[BillLineIn] = Field(min_length=1, max_length=500)
    diagnosis: str = Field(default="", max_length=SHORT_TEXT)
    procedure: str = Field(default="", max_length=SHORT_TEXT)
    discount: Money = Field(default=Decimal(0), ge=0)
    printed_total: Optional[Money] = Field(default=None, ge=0)
    condition_type: Optional[ConditionType] = Field(
        default=None, description="Only set this from the policyholder's answer or the insurer's letter.")
    room_priced_by_category: dict[Category, bool] = Field(
        default_factory=dict, description="The policyholder's answer to Q-ROOM-PRICING, per category.")

    @model_validator(mode="after")
    def _check(self) -> "ClaimIn":
        if self.admission and self.discharge and self.discharge < self.admission:
            raise ValueError("discharge is before admission")
        ids = [line.line_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("line_id values must be unique")
        return self


class PolicyIn(_In):
    """The policy schedule for the policy year of the claim."""

    policy_no: str = _id()
    sum_insured: Money = Field(gt=0)
    period_start: dt.date
    period_end: dt.date
    first_inception: dt.date
    holder: str = Field(default="", max_length=200)
    insurer: str = Field(default="", max_length=200)
    product: str = Field(default="", max_length=200)
    wording_uin: str = Field(default="", max_length=40, pattern=r"^$|^[A-Z]{7}\d{5}V\d{6}$|^upload:doc_[0-9a-f]{16}$",
                             description="The policy wording (from case-records get_policy). Selects that wording's "
                                         "limits; empty or unknown uses the standard Arogya Sanjeevani limits.")
    wording_source: Literal["catalogue", "uploaded", ""] = ""

    @model_validator(mode="after")
    def _check(self) -> "PolicyIn":
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        if self.first_inception > self.period_start:
            raise ValueError("first_inception is after period_start")
        return self


class PastClaimIn(_In):
    """An earlier claim on the same policy, from claim history."""

    claim_id: str = _id()
    policy_no: str = _id()
    admission: dt.date
    status: str = Field(min_length=1, max_length=32)
    settled_amount: Money = Field(ge=0)
    diagnosis: str = Field(default="", max_length=SHORT_TEXT)
    procedure: str = Field(default="", max_length=SHORT_TEXT)


class CaseIn(_In):
    """Everything the engine needs for one claim."""

    claim: ClaimIn
    policy: PolicyIn
    history: list[PastClaimIn] = Field(default_factory=list, max_length=200)


class LetterRowIn(_In):
    """One deduction row on the insurer's settlement letter."""

    row_id: str = _id()
    particulars: str = Field(min_length=1, max_length=SHORT_TEXT)
    amount: Money = Field(ge=0)
    reason: str = Field(default="", max_length=SHORT_TEXT)
    kind: Optional[RowKind] = Field(default=None, description="Leave null to classify from the wording.")


class LetterIn(_In):
    """The insurer's decision, as extracted from the letter."""

    letter_id: str = _id()
    letter_type: Literal["settlement", "rejection"]
    claimed_amount: Money = Field(ge=0)
    rows: list[LetterRowIn] = Field(default_factory=list, max_length=50)
    paid_amount: Money = Field(ge=0)
    copay_amount: Optional[Money] = Field(default=None, ge=0)
    rejection_reason: str = Field(default="", max_length=LONG_TEXT)

    @model_validator(mode="after")
    def _check(self) -> "LetterIn":
        ids = [r.row_id for r in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("row_id values must be unique")
        if {"COPAY", "REJECTION"} & set(ids):
            raise ValueError("COPAY and REJECTION are reserved row IDs")
        return self


# =========================================================================== outputs


class FactOut(_Out):
    fact_id: str
    kind: str
    text: str
    amount: Optional[float]
    formula: str
    rule_ref: str
    line_ids: list[str]
    inputs: dict[str, Any]


class DeductionOut(_Out):
    deduction_id: str
    kind: DeductionKind
    amount: float
    description: str
    formula: str
    rule_ref: str
    line_ids: list[str]
    fact_id: str


class QuestionOut(_Out):
    question_id: str
    text: str
    reason: str
    line_ids: list[str]


class LineViewOut(_Out):
    line_id: str
    description: str
    amount: float
    gst: float
    category: Category
    category_source: Literal["input", "keyword", "unknown"]
    non_payable: bool
    non_payable_source: Literal["input", "keyword", "default"]
    room_linked: Optional[bool]


class SettlementOut(_Out):
    """What the policy wording says should be paid. Cite figures by ``fact_id``."""

    claim_id: str
    status: Status
    claimed_amount: float
    deductions: list[DeductionOut]
    total_deductions: float
    admissible_amount: Optional[float]
    copay_amount: Optional[float]
    payable_amount: Optional[float]
    facts: list[FactOut]
    questions: list[QuestionOut]
    lines: list[LineViewOut]
    warnings: list[str]


class HypothesisMatchOut(_Out):
    hypothesis_id: str
    correct: bool
    title: str
    amount: float
    detail: str
    line_ids: list[str]


class RowAuditOut(_Out):
    """The verdict on one letter row."""

    row_id: str
    particulars: str
    kind: RowKind
    kind_source: Literal["input", "keyword"]
    insurer_amount: float
    policy_amount: Optional[float]
    difference: Optional[float]
    verdict: Verdict
    method: Optional[str]
    explanation: str
    matches: list[HypothesisMatchOut]
    tested: list[str]
    exhaustive: bool
    rule_ref: str
    policy_fact_ids: list[str]
    questions: list[QuestionOut]


class LetterAuditOut(_Out):
    """Every row's verdict, plus the rupee summary (amounts after co-pay)."""

    letter_id: str
    rows: list[RowAuditOut]
    policy_payable: Optional[float]
    insurer_paid: float
    gap: Optional[float]
    unverified_amount: Optional[float]
    disputable_amount: Optional[float]
    overpaid_amount: Optional[float]
    letter_arithmetic_gap: float
    policy_deductions_not_on_letter: list[str]
    questions: list[QuestionOut]
    warnings: list[str]
    settlement: SettlementOut


class HypothesisOut(_Out):
    hypothesis_id: str
    kind: RowKind
    correct: bool
    method_only: bool
    title: str
    description: str


class HypothesisListOut(_Out):
    hypotheses: list[HypothesisOut]
