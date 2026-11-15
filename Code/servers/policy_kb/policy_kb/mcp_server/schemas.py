"""Typed outputs of the policy-kb MCP tools (pydantic).

They describe the dicts built by ``policy_kb.tools`` (``search_clauses_result``,
``get_clause_result``, ``clauses_for_rule_result``), so the MCP server and the
in-process LangChain tools return the same shape. Pinned by
``tests/snapshots/policy_kb_tools.json``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordingOut(_Out):
    """Which policy wording the clauses come from."""

    insurer: str
    product: str
    uin: str = Field(description="IRDAI unique identification number of the product")
    version: str
    source_url: str
    downloaded_on: str = Field(description="ISO date the wording was downloaded")
    sha256: str = Field(description="SHA-256 of the downloaded file")
    synthetic: bool = Field(description="True for a test wording: never show its text to a user as policy wording")
    source: Literal["catalogue", "uploaded"] = Field(description="catalogue: a reviewed, pre-stored wording; "
                                                                 "uploaded: the policyholder's own PDF")
    reviewed: bool = Field(description="False for uploaded wordings: say the wording was not reviewed when "
                                       "quoting it")


class ClauseHitOut(_Out):
    clause_id: str = Field(description="As printed in the wording, e.g. C.1.1; pass to get_clause")
    title: str
    section: str
    text: str = Field(description="The clause's own text, exactly as extracted")
    score: float = Field(description="Ranking score; only meaningful for ordering")
    page_start: Optional[int]
    page_end: Optional[int]
    ranks: dict[str, Optional[int]] = Field(description="1-based rank in each retriever (bm25, vector, rerank)")
    citation: str = Field(description="Wording and clause number, to show next to a quote")


class SearchClausesOut(_Out):
    query: str
    wording: WordingOut
    synthetic: bool
    hits: list[ClauseHitOut]


class ClauseOut(_Out):
    found: bool = Field(description="False when the wording has no such clause; then do not cite it")
    clause_id: str
    title: str
    section: str
    parent_id: Optional[str]
    text: str
    page_start: Optional[int]
    page_end: Optional[int]
    codes: list[str] = Field(description="IRDAI exclusion codes printed in the clause, e.g. Excl01")
    citation: Optional[str]
    wording: WordingOut
    synthetic: bool


class RuleClausesOut(_Out):
    rule_ref: str
    where: str = Field(description="Where in the clauses the rule is stated (reviewed note)")
    differs_from_engine: Optional[str] = Field(
        description="Set when the wording and the settlement engine disagree; a verdict-policy decision")
    clauses: list[ClauseOut] = Field(description="The first is the clause to cite; may be empty if the wording "
                                                 "does not address the rule")
    wording: WordingOut
    synthetic: bool


class PolicySummaryOut(_Out):
    wording_uin: str = Field(description="Pass to the other policy-kb tools as wording_uin")
    insurer: str
    product: str
    version: str
    source: Literal["catalogue", "uploaded"]
    reviewed: bool
    index_available: bool
    clause_count: Optional[int]
    has_rule_map: bool = Field(description="False: clauses_for_rule returns NO_RULE_MAP; use search_clauses")


class ListPoliciesOut(_Out):
    default_wording_uin: str
    policies: list[PolicySummaryOut]


class PageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, le=10000)
    text: str = Field(max_length=20000, description="Visible text of the page only (case-records page.text), "
                                                    "never hidden_text")


class RegisterUploadOut(_Out):
    wording_uin: str = Field(description="upload:doc_<id>; store it on the case (case-records set_wording)")
    case_id: str
    document_id: str
    clause_count: int
    structure: Literal["clauses", "pages"] = Field(description="pages: numbered clauses weren't recognised, so "
                                                               "each page is one searchable chunk")
    in_scope: bool = Field(description="False when the text doesn't look like an Arogya Sanjeevani policy")
    detected_uin: Optional[str]
    catalogue_match: Optional[str] = Field(description="Set when the detected UIN is in the catalogue: the "
                                                       "reviewed copy can be used instead")
    reviewed: bool
    warnings: list[str]
