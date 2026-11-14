"""Tool results over a ``PolicyKB``, and the same tools as in-process LangChain tools.

The three result builders are the single definition of what the policy-kb tools
return. The policy-kb MCP server (``policy_kb.mcp_server``) validates them against
its pydantic output models, and ``make_tools`` wraps them as LangChain tools, so an
agent sees exactly the same dict from either::

    search_clauses_result(kb, "why did they cut my medicine bill", k=5)
        -> {"query", "wording", "synthetic", "hits": [{clause_id, title, section, text, score, ..., citation}]}
    get_clause_result(kb, "C.1.1")
        -> {"found": True, "clause_id", "title", "text", ..., "citation", "wording", "synthetic"}
    clauses_for_rule_result(kb, "copay")
        -> {"rule_ref", "where", "differs_from_engine", "clauses": [get_clause results], "wording", "synthetic"}

In-process use (no MCP server)::

    from policy_kb import load_default_kb
    from policy_kb.tools import make_tools
    async with ClaimClearToolkit(local_tools=make_tools(load_default_kb())) as tk:
        tk.for_agent("policy_analyst")

``synthetic`` is true for test wordings: their text must never be shown to a user
as policy wording.
"""

from __future__ import annotations

from typing import Any

from .kb import PolicyKB
from .models import Clause

MAX_K = 10


class PolicyKBError(Exception):
    """An error the caller can act on. The MCP server turns it into ``{"code", "message", "retryable"}``."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def citation(kb: PolicyKB, clause_id: str) -> str:
    """E.g. "Go Digit General Insurance Limited Arogya Sanjeevani Policy (GODHLIP24179V022324), clause C.1.1"."""
    who = f"{kb.info.insurer} {kb.info.product}".strip()
    return f"{who} ({kb.info.uin}), clause {clause_id}" if kb.info.uin else f"{who}, clause {clause_id}"


def wording_result(kb: PolicyKB) -> dict:
    i = kb.info
    uploaded = i.uin.startswith("upload:")
    return {"insurer": i.insurer, "product": i.product, "uin": i.uin, "version": i.version,
            "source_url": i.source_url, "downloaded_on": i.downloaded_on, "sha256": i.sha256,
            "synthetic": i.synthetic, "source": "uploaded" if uploaded else "catalogue",
            "reviewed": (not uploaded) and bool(kb.rule_map().get("rules"))}


def _clause(kb: PolicyKB, c: Clause) -> dict:
    return {"found": True, "clause_id": c.clause_id, "title": c.title, "section": c.section,
            "parent_id": c.parent_id, "text": c.text, "page_start": c.page_start, "page_end": c.page_end,
            "codes": list(c.codes), "citation": citation(kb, c.clause_id), "wording": wording_result(kb),
            "synthetic": kb.info.synthetic}


def search_clauses_result(kb: PolicyKB, query: str, k: int = 5) -> dict:
    """The ``k`` (1–10) clauses most relevant to ``query``, each with a citation."""
    if not query or not query.strip():
        raise PolicyKBError("EMPTY_QUERY", "query is empty; pass the policyholder's question or policy terms")
    k = max(1, min(int(k), MAX_K))
    hits = [{"clause_id": h.clause_id, "title": h.title, "section": h.section, "text": h.text,
             "score": h.score, "page_start": h.page_start, "page_end": h.page_end,
             "ranks": dict(h.ranks), "citation": citation(kb, h.clause_id)}
            for h in kb.search(query, k=k)]
    return {"query": query, "wording": wording_result(kb), "synthetic": kb.info.synthetic, "hits": hits}


def get_clause_result(kb: PolicyKB, clause_id: str) -> dict:
    """One clause by its printed number. ``found`` is false (not an error) when there is no such clause,
    so the critic can check a citation without handling an exception."""
    c = kb.get_clause(clause_id)
    if c is None:
        return {"found": False, "clause_id": clause_id, "title": "", "section": "", "parent_id": None, "text": "",
                "page_start": None, "page_end": None, "codes": [], "citation": None,
                "wording": wording_result(kb), "synthetic": kb.info.synthetic}
    return _clause(kb, c)


def clauses_for_rule_result(kb: PolicyKB, rule_ref: str) -> dict:
    """The clauses behind a settlement-engine ``rule_ref`` (from a deduction or fact), from the reviewed
    rule map of this wording. The first clause is the one to cite."""
    rules = kb.rule_map().get("rules")
    if not rules:
        raise PolicyKBError("NO_RULE_MAP", f"there is no reviewed rule map for wording {kb.info.key!r}; "
                                           "use search_clauses and cite the engine's rule summary as a summary")
    entry = rules.get(rule_ref)
    if entry is None:
        raise PolicyKBError("UNKNOWN_RULE", f"unknown rule_ref {rule_ref!r}; known: {', '.join(sorted(rules))}")
    return {"rule_ref": rule_ref, "where": entry.get("where", ""),
            "differs_from_engine": entry.get("differs_from_engine"),
            "clauses": [_clause(kb, c) for c in kb.clauses_for_rule(rule_ref)],
            "wording": wording_result(kb), "synthetic": kb.info.synthetic}


def list_policies_result(kb: PolicyKB) -> dict:
    """The one wording an in-process ``kb`` serves, in the shape of the MCP ``list_policies`` result."""
    w = wording_result(kb)
    uin = kb.info.uin or kb.info.key
    return {"default_wording_uin": uin, "policies": [{
        "wording_uin": uin, "insurer": w["insurer"], "product": w["product"], "version": w["version"],
        "source": w["source"], "reviewed": w["reviewed"], "index_available": True,
        "clause_count": len(kb.clauses), "has_rule_map": bool(kb.rule_map().get("rules"))}]}


def make_tools(kb: PolicyKB) -> dict[str, Any]:
    """``{"search_clauses", "get_clause", "clauses_for_rule"}`` as LangChain tools bound to ``kb``,
    returning the same dicts as the MCP server.

    Errors come back the way an MCP tool's do: the tool message text is
    ``Error executing tool <name>: {"code", "message", "retryable"}`` (no exception), so
    ``claimclear_tools.results.tool_error`` reads both alike."""
    import json

    from langchain_core.tools import ToolException, tool

    def run(fn):
        try:
            return fn()
        except PolicyKBError as exc:
            raise ToolException(json.dumps({"code": exc.code, "message": exc.message, "retryable": exc.retryable}))

    @tool
    def search_clauses(query: str, k: int = 5) -> dict:
        """Search the policy wording for the clauses most relevant to a question. Use the policyholder's words or
        policy terms. Returns up to k clauses (at most 10) in "hits", each with clause_id, title, text, pages and
        a citation."""
        return run(lambda: search_clauses_result(kb, query, k))

    @tool
    def get_clause(clause_id: str) -> dict:
        """Fetch one clause of the policy wording by its printed number, e.g. "C.1.1" or "Annexure A List I".
        Returns found=false if there is no such clause. Use it to check a citation before quoting it."""
        return run(lambda: get_clause_result(kb, clause_id))

    @tool
    def clauses_for_rule(rule_ref: str) -> dict:
        """The policy clauses behind a settlement-engine rule_ref, e.g. "room_rent_cap" or "copay", from a
        reviewed map. Cite the first clause. differs_from_engine, when set, says where the wording and the
        engine disagree."""
        return run(lambda: clauses_for_rule_result(kb, rule_ref))

    @tool
    def list_policies() -> dict:
        """The policy wording this knowledge base serves, with its wording_uin, insurer, product and whether it
        was reviewed."""
        return list_policies_result(kb)

    tools = {"search_clauses": search_clauses, "get_clause": get_clause, "clauses_for_rule": clauses_for_rule,
             "list_policies": list_policies}
    for name, t in tools.items():
        t.handle_tool_error = lambda exc, name=name: f"Error executing tool {name}: {exc}"
    return tools
