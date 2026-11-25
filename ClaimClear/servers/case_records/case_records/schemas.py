"""Typed outputs of the case-records MCP tools (pydantic).

Pinned by ``tests/snapshots/case_records_tools.json``. ``PolicyOut`` and
``PastClaimOut`` have exactly the fields of the settlement-engine's ``PolicyIn``
and ``PastClaimIn``, so they can be passed straight through (a test checks it).
``DocumentTextOut`` comes from the document reader (``servers/document_reader``).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from document_reader.schemas import (  # noqa: F401  the document text shape is the reader's, defined once
    AnnotationOut,
    AttachmentOut,
    DocumentTextOut,
    FormFieldOut,
    HiddenReason,
    PageOut,
    SpanOut,
)
from pydantic import BaseModel, ConfigDict, Field

CASE_ID = Field(pattern=r"^case_[0-9a-f]{16}$", description="Case ID from the upload, e.g. case_3fa2c1d0e9b84a77")
DOC_ID = Field(pattern=r"^doc_[0-9a-f]{16}$", description="Document ID from list_case_documents")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentInfoOut(_Out):
    document_id: str
    role: Literal["bill", "settlement_letter", "discharge_summary", "policy_wording", "policy_schedule", "other"] = \
        Field(description="What the document is in this case, as given at upload")
    media_type: str
    size_bytes: int
    sha256: str
    page_count: Optional[int] = Field(None, description="Pages in the document; null if it couldn't be counted")
    name: str = Field("", description="The user's own file name, when the app recorded it; empty otherwise")
    summary: str = Field("", description="One line on what the document is, when the app recorded it")


class CaseDocumentsOut(_Out):
    case_id: str
    policy_no: str
    documents: list[DocumentInfoOut]


class PolicyOut(_Out):
    policy_no: str
    sum_insured: float
    period_start: dt.date
    period_end: dt.date
    first_inception: dt.date
    holder: str
    insurer: str
    product: str
    wording_uin: str = Field(description="The policy wording to cite: an IRDAI UIN from the catalogue, or "
                                         "upload:doc_<id> for a policy the user uploaded. Pass it to policy-kb.")
    wording_source: Literal["catalogue", "uploaded"]


class PastClaimOut(_Out):
    claim_id: str
    policy_no: str
    admission: dt.date
    status: str
    settled_amount: float
    diagnosis: str
    procedure: str


class ClaimHistoryOut(_Out):
    policy_no: str
    scope: Literal["current_period", "all"]
    claims: list[PastClaimOut]


class WordingOut(_Out):
    """Which policy wording the case is checked against, and whether to ask the user for theirs."""

    case_id: str
    wording_uin: str = Field(description="The wording get_policy returns and policy-kb is called with: a catalogue "
                                         "UIN, or upload:doc_<id> for the user's indexed upload.")
    wording_source: Literal["catalogue", "uploaded"]
    status: Literal["selected", "uploaded", "from_schedule", "not_reviewed", "not_printed", "other_product"] = Field(
        description="selected: the user picked a catalogue wording. uploaded: their own wording is indexed. "
                    "from_schedule: the UIN on the policy schedule is a reviewed wording. not_reviewed: the "
                    "schedule names a wording ClaimClear hasn't reviewed (the standard one is used for now). "
                    "not_printed: no UIN on an Arogya Sanjeevani schedule, or no schedule (the standard one is "
                    "used). other_product: the schedule prints no UIN and isn't an Arogya Sanjeevani policy.")
    schedule_wording_uin: str = Field(description="The UIN printed on the policy schedule; empty if none.")
    wording_needed: bool = Field(description="True: ask the user to upload their policy wording (or index "
                                             "wording_document_id if the case already has one).")
    wording_document_id: str = Field(description="A document of the case with the role policy_wording; empty if "
                                                 "none.")
    note: str = Field(description="What to tell or ask the user, in plain words.")
    cite_clauses: bool = Field(description="False: wording_uin is not this policy's wording (another product); "
                                           "never quote its clauses as the user's terms.")
