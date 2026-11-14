"""Typed hand-off messages between the agents, and the plan object shown to the user.

Server data inside a hand-off keeps the server's own shape (a ``dict`` that
``tools.validate`` can check against the exported schema); these models only add
the structure around it. ``extra="forbid"`` everywhere: an agent can't slip extra
keys through a hand-off.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentName = Literal["supervisor", "document_reader", "policy_analyst", "settlement_auditor", "critic",
                    "explainer", "grievance_agent"]
CASE_ID = r"^case_[0-9a-f]{16}$"
DOC_ID = r"^doc_[0-9a-f]{16}$"


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- plan


class PlanStep(_Msg):
    step_id: str = Field(pattern=r"^S\d+$")
    agent: AgentName
    goal: str = Field(min_length=1, max_length=300)
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"


class Plan(_Msg):
    """The plan the supervisor shows the user. A replan bumps ``version`` and says why."""

    version: int = Field(default=1, ge=1)
    steps: list[PlanStep] = Field(min_length=1)
    replan_reason: str = Field(default="", description="Empty for the first plan; the tool result that contradicted it")

    @model_validator(mode="after")
    def _check(self) -> "Plan":
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step_id values must be unique")
        if self.version > 1 and not self.replan_reason:
            raise ValueError("a replan must say why (replan_reason)")
        return self


# --------------------------------------------------------------------------- specialists


class UnreadablePage(_Msg):
    document_id: str = Field(pattern=DOC_ID)
    pages: list[int] = Field(min_length=1)
    reason: Literal["ocr_unavailable", "ocr_failed", "unreadable"]


class ReaderHandoff(_Msg):
    """Document reader -> supervisor: what the documents say, each field with its source span."""

    case_id: str = Field(pattern=CASE_ID)
    claim: Optional[dict[str, Any]] = Field(default=None, description="settlement-engine ClaimIn")
    letter: Optional[dict[str, Any]] = Field(default=None, description="settlement-engine LetterIn")
    sources: dict[str, str] = Field(default_factory=dict, description="field path -> span_id")
    unreadable: list[UnreadablePage] = Field(default_factory=list,
                                             description="Pages that could not be read: take the missing-document edge")


class AnalystHandoff(_Msg):
    """Policy analyst -> supervisor: the policy, earlier claims and the clauses found."""

    policy: dict[str, Any] = Field(description="case-records PolicyOut, unchanged")
    history: list[dict[str, Any]] = Field(default_factory=list, description="case-records PastClaimOut, unchanged")
    clauses: dict[str, dict[str, Any]] = Field(default_factory=dict, description="clause_id -> get_clause result")


class AuditorHandoff(_Msg):
    """Settlement auditor -> supervisor: the engine's settlement and a verdict per letter row."""

    settlement: dict[str, Any] = Field(description="settlement-engine SettlementOut")
    row_audits: dict[str, dict[str, Any]] = Field(default_factory=dict, description="row_id -> RowAuditOut")
    questions: list[dict[str, Any]] = Field(default_factory=list, description="QuestionOut to ask through interrupt()")
    replanned_rows: list[str] = Field(default_factory=list,
                                      description="Rows re-tested with every hypothesis after a partial test (replan trace)")


class CriticFailure(_Msg):
    check: Literal["figure_not_from_engine", "verdict_wording", "disputable_total", "clause_not_found",
                   "forbidden_phrase"]
    detail: str


class CriticReport(_Msg):
    """Critic -> supervisor. ``attempt`` 2 that fails means: fall back to the plain verdict table."""

    passed: bool
    attempt: Literal[1, 2] = 1
    failures: list[CriticFailure] = Field(default_factory=list)
    disputable_amount: Optional[Decimal] = Field(default=None, description="letter_audit.disputable_amount")

    @model_validator(mode="after")
    def _check(self) -> "CriticReport":
        if self.passed == bool(self.failures):
            raise ValueError("passed must be true exactly when there are no failures")
        return self


class ExplanationSentence(_Msg):
    text: str = Field(min_length=1, max_length=600)
    fact_ids: list[str] = Field(default_factory=list, description="settlement facts the sentence states, e.g. F-PAYABLE")
    row_ids: list[str] = Field(default_factory=list)
    clause_ids: list[str] = Field(default_factory=list)


class ExplainerDraft(_Msg):
    """Explainer -> critic: every sentence tied to the facts, rows or clauses it states."""

    sentences: list[ExplanationSentence] = Field(min_length=1)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


class GrievanceDraft(_Msg):
    """Grievance agent -> approval gate: the exact text and its SHA-256, on disputable rows only."""

    case_id: str = Field(pattern=CASE_ID)
    claim_id: str = Field(min_length=1, max_length=100)
    row_ids: list[str] = Field(min_length=1)
    text: str = Field(min_length=1, max_length=20000)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _check(self) -> "GrievanceDraft":
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_sha256:
            raise ValueError("text_sha256 is not the SHA-256 of text: an edit needs a fresh hash and approval")
        return self

    @classmethod
    def build(cls, case_id: str, claim_id: str, row_ids: list[str], text: str) -> "GrievanceDraft":
        return cls(case_id=case_id, claim_id=claim_id, row_ids=row_ids, text=text,
                   text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


HANDOFFS: tuple[type[BaseModel], ...] = (Plan, ReaderHandoff, AnalystHandoff, AuditorHandoff, CriticReport,
                                         ExplainerDraft, GrievanceDraft)
