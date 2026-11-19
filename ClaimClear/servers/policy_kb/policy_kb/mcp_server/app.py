"""The policy-kb MCP server.

Read-only tools over the policy catalogue (``wording_uin`` picks the wording; default: the
catalogue's default wording):

    list_policies     the wordings policy-kb can serve (catalogue, plus a case's own upload)
    search_clauses    the clauses most relevant to a question (hybrid search + query rewriting)
    get_clause        one clause by its printed number; found=false if there is none
    clauses_for_rule  the clauses behind a settlement-engine rule_ref, from a reviewed map

One write tool, for the **app only** (it is in no agent's tool list):

    register_uploaded_wording  index the visible text of a policy the user uploaded, for one case

The results are built by ``policy_kb.tools``, so they are the same dicts the in-process LangChain
tools return. Indexes are loaded on first use and re-loaded when their file changes, so the server
can start before an index exists and picks up a rebuild without a restart.

Errors the caller can act on come back as a tool error whose text is JSON:
``{"code": "...", "message": "...", "retryable": false}``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Callable, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from .. import INDEX_ENV, default_index_path
from ..catalogue import CATALOGUE_ENV, PolicyLibrary, default_catalogue_path
from ..kb import PolicyKB
from ..openrouter import OpenRouterError
from ..rewrite import make_rewriter
from ..tools import PolicyKBError, clauses_for_rule_result, get_clause_result, search_clauses_result
from .schemas import ClauseOut, ListPoliciesOut, PageIn, RegisterUploadOut, RuleClausesOut, SearchClausesOut

log = logging.getLogger("claimclear.policy_kb")

SERVER_NAME = "policy-kb"
REWRITER_ENV = "CLAIMCLEAR_POLICY_KB_REWRITER"     # none | glossary (default) | openrouter[:model] | glossary+openrouter
RERANKER_ENV = "CLAIMCLEAR_POLICY_KB_RERANKER"     # none (default) | fastembed

INSTRUCTIONS = """\
ClaimClear policy knowledge base. Searches the policyholder's policy wording and returns
clauses with their printed numbers and a citation.

Rules for callers:
- Pass the case's wording_uin (from case-records get_policy) to every tool; for an uploaded
  wording (upload:doc_...) also pass the case_id.
- Quote only text returned by these tools, and cite it with its "citation".
- Before quoting a clause ID from memory or from another agent, check it with get_clause;
  if found is false, do not cite it.
- If wording.reviewed is false (an uploaded wording), say the wording was not reviewed.
- If synthetic is true the wording is a test wording: never present it to a user as their policy.
- To explain a settlement-engine deduction, call clauses_for_rule with its rule_ref and cite
  the first clause. If differs_from_engine is set, say the wording and the engine differ.
- These tools never compute or check rupee amounts; the settlement-engine does that.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
READ_META = {"access": "read"}
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE_META = {"access": "write", "caller": "app"}

Query = Annotated[str, Field(min_length=1, max_length=500,
                             description="The policyholder's question or policy terms, e.g. 'why did they cut "
                                         "my medicine bill'")]
TopK = Annotated[int, Field(ge=1, le=10, description="How many clauses to return (1-10)")]
ClauseId = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9 .\-–]+$",
                                description="Printed clause number, e.g. 'C.1.1', '5.2', 'Annexure A List I'")]
RuleRef = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$",
                               description="A settlement-engine rule_ref, e.g. 'room_rent_cap', 'copay'")]
WordingUin = Annotated[Optional[str], Field(
    pattern=r"^[A-Z]{7}\d{5}V\d{6}$|^upload:doc_[0-9a-f]{16}$",
    description="The case's wording (case-records get_policy wording_uin). Omit for the default wording.")]
CaseIdOpt = Annotated[Optional[str], Field(pattern=r"^case_[0-9a-f]{16}$",
                                           description="Required with an uploaded wording (upload:doc_...)")]
CaseId = Annotated[str, Field(pattern=r"^case_[0-9a-f]{16}$", description="The case the upload belongs to")]
DocId = Annotated[str, Field(pattern=r"^doc_[0-9a-f]{16}$", description="The uploaded policy's document_id")]


def _error(code: str, message: str, retryable: bool = False) -> ToolError:
    return ToolError(json.dumps({"code": code, "message": message, "retryable": retryable}))


def build_library(kb: Optional[PolicyKB] = None, index_path: Optional[str | Path] = None,
                  catalogue_path: Optional[str | Path] = None, rewriter: Optional[str] = None,
                  reranker: Optional[str] = None) -> PolicyLibrary:
    """Where the wordings come from: an in-memory index (tests), one index file, or the catalogue."""
    rw_name = rewriter or os.environ.get(REWRITER_ENV, "glossary")
    rr_name = reranker or os.environ.get(RERANKER_ENV, "none")
    rw = make_rewriter(rw_name)

    def loader(p: Path) -> PolicyKB:
        return PolicyKB.load(p, reranker=rr_name, rewriter=rw)

    if kb is not None:
        log.info("serving an in-memory index: %s", kb.info.key)
        return PolicyLibrary.from_kb(kb, default_index_path().parent, loader)
    if not index_path and not catalogue_path and os.environ.get(INDEX_ENV) and not os.environ.get(CATALOGUE_ENV):
        index_path = os.environ[INDEX_ENV]          # an index set explicitly wins over the default catalogue
    if index_path:
        log.info("serving one index %s; rewriter %s; reranker %s", index_path, rw_name, rr_name)
        return PolicyLibrary.from_index(Path(index_path), loader)
    cat = Path(catalogue_path) if catalogue_path else default_catalogue_path()
    if cat.exists():
        lib = PolicyLibrary.from_catalogue(cat, default_index_path().parent, loader)
        log.info("catalogue %s: %d wording(s), default %s; rewriter %s; reranker %s", cat, len(lib.entries),
                 lib.default_uin, rw_name, rr_name)
        return lib
    log.info("no catalogue at %s; serving %s", cat, default_index_path())
    return PolicyLibrary.from_index(default_index_path(), loader)


def create_server(kb: Optional[PolicyKB] = None, index_path: Optional[str | Path] = None,
                  rewriter: Optional[str] = None, reranker: Optional[str] = None,
                  catalogue_path: Optional[str | Path] = None, library: Optional[PolicyLibrary] = None) -> MCPServer:
    """Build the server.

    ``kb`` serves one index already in memory (tests); ``index_path`` serves one index file; otherwise the
    catalogue (``$CLAIMCLEAR_POLICY_CATALOGUE`` or ``dev_data/wordings/catalogue.json``) is used, falling back to
    the single default index (``$CLAIMCLEAR_POLICY_KB_INDEX`` or ``var/policy_kb/index.json``).
    """
    lib = library or build_library(kb, index_path, catalogue_path, rewriter, reranker)
    server = MCPServer(name=SERVER_NAME, title="ClaimClear policy knowledge base", version="0.2.0",
                       instructions=INSTRUCTIONS)

    def guarded(fn: Callable[[], dict], model):
        try:
            return model.model_validate(fn())
        except PolicyKBError as exc:
            raise _error(exc.code, exc.message, exc.retryable)
        except OpenRouterError as exc:          # query embedding or LLM rewriting failed
            retryable = exc.status is None or exc.status in (429, 500, 502, 503, 504)
            raise _error("UPSTREAM_UNAVAILABLE", f"the embedding or rewriting service failed: {exc}", retryable)

    @server.tool(
        title="List policies",
        description=(
            "The policy wordings available: the reviewed catalogue, plus the case's own uploaded wording when "
            "case_id is given. Each has a wording_uin to pass to the other tools. Use it to show the policy "
            "picker or to confirm which wording a case uses."),
        annotations=READ_ONLY, meta=READ_META)
    def list_policies(insurer: Annotated[Optional[str], Field(max_length=100)] = None,
                      query: Annotated[Optional[str], Field(max_length=100)] = None,
                      case_id: CaseIdOpt = None) -> ListPoliciesOut:
        return guarded(lambda: lib.list(insurer, query, case_id), ListPoliciesOut)

    @server.tool(
        title="Search clauses",
        description=(
            "Search the policy wording for the clauses most relevant to a question, in the policyholder's words "
            "or policy terms. Returns up to k clauses in 'hits', best first, each with clause_id, title, text, "
            "pages and a citation. Quote only returned text."),
        annotations=READ_ONLY, meta=READ_META)
    def search_clauses(query: Query, k: TopK = 5, wording_uin: WordingUin = None,
                       case_id: CaseIdOpt = None) -> SearchClausesOut:
        return guarded(lambda: search_clauses_result(lib.resolve(wording_uin, case_id), query, k), SearchClausesOut)

    @server.tool(
        title="Get clause",
        description=(
            "Fetch one clause of the policy wording by its printed number, e.g. 'C.1.1' or 'Annexure A List I' "
            "(or 'Page 3' for an uploaded wording indexed by page). Returns found=false if the wording has no "
            "such clause. Use it to check a citation before quoting it."),
        annotations=READ_ONLY, meta=READ_META)
    def get_clause(clause_id: ClauseId, wording_uin: WordingUin = None, case_id: CaseIdOpt = None) -> ClauseOut:
        return guarded(lambda: get_clause_result(lib.resolve(wording_uin, case_id), clause_id), ClauseOut)

    @server.tool(
        title="Clauses for an engine rule",
        description=(
            "The policy clauses behind a settlement-engine rule_ref (from a deduction or fact), e.g. "
            "'room_rent_cap', 'proportionate_deduction', 'copay', from a map reviewed against the wording. Cite the "
            "first clause. 'differs_from_engine', when set, says where the wording and the engine disagree. "
            "Uploaded wordings have no map: NO_RULE_MAP, use search_clauses."),
        annotations=READ_ONLY, meta=READ_META)
    def clauses_for_rule(rule_ref: RuleRef, wording_uin: WordingUin = None,
                         case_id: CaseIdOpt = None) -> RuleClausesOut:
        return guarded(lambda: clauses_for_rule_result(lib.resolve(wording_uin, case_id), rule_ref), RuleClausesOut)

    @server.tool(
        title="Register uploaded wording",
        description=(
            "APP ONLY, not for agents. Index the visible text of a policy wording the user uploaded (pages from "
            "case-records get_document_text, page.text only) for one case. Returns its wording_uin "
            "(upload:doc_...), how it was indexed, and whether it looks like an Arogya Sanjeevani policy."),
        annotations=WRITE, meta=WRITE_META)
    def register_uploaded_wording(case_id: CaseId, document_id: DocId,
                                  pages: Annotated[list[PageIn], Field(min_length=1, max_length=300)]
                                  ) -> RegisterUploadOut:
        return guarded(lambda: lib.register_upload(case_id, document_id, [p.model_dump() for p in pages]),
                       RegisterUploadOut)

    return server
