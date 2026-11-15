"""Stand-ins for the policy-kb tools, used only when the policy-kb server is not connected.

They have the real names and return the real shapes (empty), so agent prompts and
tool lists don't change. They find nothing, and the critic must treat every
citation as missing while they are in use (``stub`` is true in every result).
"""

from __future__ import annotations

from langchain_core.tools import tool

_NO_WORDING = {"insurer": "", "product": "", "uin": "", "version": "", "source_url": "", "downloaded_on": "",
               "sha256": "", "synthetic": True}


@tool
def search_clauses(query: str, k: int = 5) -> dict:
    """STUB (policy-kb not connected): search the policy wording for clauses. Returns no clauses."""
    return {"query": query, "wording": dict(_NO_WORDING), "synthetic": True, "hits": [], "stub": True}


@tool
def get_clause(clause_id: str) -> dict:
    """STUB (policy-kb not connected): fetch one clause by ID. Always reports it as not found."""
    return {"found": False, "clause_id": clause_id, "title": "", "section": "", "parent_id": None, "text": "",
            "page_start": None, "page_end": None, "codes": [], "citation": None, "wording": dict(_NO_WORDING),
            "synthetic": True, "stub": True}


@tool
def clauses_for_rule(rule_ref: str) -> dict:
    """STUB (policy-kb not connected): the clauses behind an engine rule_ref. Returns no clauses."""
    return {"rule_ref": rule_ref, "where": "", "differs_from_engine": None, "clauses": [],
            "wording": dict(_NO_WORDING), "synthetic": True, "stub": True}


@tool
def list_policies(insurer: str = "", query: str = "", case_id: str = "") -> dict:
    """STUB (policy-kb not connected): the available policy wordings. Returns none."""
    return {"default_wording_uin": "", "policies": [], "stub": True}


POLICY_KB_STUBS = {"search_clauses": search_clauses, "get_clause": get_clause, "clauses_for_rule": clauses_for_rule,
                   "list_policies": list_policies}
