"""The chat agent: answers the policyholder's own questions about their claim and their policy.

``await rule_answer(question, state, toolkit)`` returns ``{"text", "sources", "how"}``.

The model-based answer lives in ``chat.py`` (streaming, checked as it streams); this module is the rule-based
answer it falls back to, and the helpers both share:

* a rule-based answer to the specific question: a letter row (by ID or topic: room
  rent, GST, proportionate, co-pay, consumables, rejection ...), a clause by number, the disputable amount and
  the grievance, the totals, the filing status, a summary; anything else is answered from the policy wording
  (``search_clauses``), quoting the clause and its citation.

Tools: ``AGENT_TOOLS["qa_agent"]`` (read only: ``search_clauses``, ``get_clause``, ``clauses_for_rule``,
``grievance_status``), through a ``ScopedToolkit``. The agent never computes a figure.
"""

from __future__ import annotations

import re
from typing import Optional

from claimclear_contracts.verdicts import wording_for
from claimclear_tools.results import ClaimClearToolError

from .checks import inr
from .services import ScopedToolkit

QA_AGENT = "qa_agent"
CLAUSE_ID = re.compile(r"\b(?:clause\s+)?([A-H]\.\d+(?:\.\d+)*)\b", re.I)
ROW_ID = re.compile(r"\b(R\d{1,2}|COPAY|CO-PAY|REJECTION)\b", re.I)
TOPICS = {  # words in a question -> words in a letter row's particulars / kind
    "room": ("room",), "rent": ("room",), "icu": ("icu",), "gst": ("gst",), "tax": ("gst",),
    "proportion": ("proportion",), "associated": ("proportion",), "co-pay": ("co-pay", "copay"),
    "copay": ("co-pay", "copay"), "co pay": ("co-pay", "copay"), "consumable": ("non-payable", "consumable"),
    "non-payable": ("non-payable",), "non payable": ("non-payable",), "gloves": ("non-payable",),
    "pharmacy": ("pharmacy", "medicine"), "medicine": ("pharmacy", "medicine"), "reject": ("reject",),
    "cataract": ("cataract",), "ambulance": ("ambulance",), "duplicate": ("duplicate",),
}
DISPUTE = ("dispute", "disputable", "grievance", "appeal", "complain", "complaint", "recover", "refund", "get back",
           "wrong", "unfair", "challenge", "ombudsman")
TOTALS = ("payable", "how much", "total", "paid", "settle", "settlement amount", "amount", "short")
STATUS = ("status", "reference", "filed", "submitted", "track")
SUMMARY = ("summary", "summarise", "summarize", "explain", "overview", "what happened", "why")

def _rows(state: dict) -> list[dict]:
    return (state.get("letter_audit") or {}).get("rows", []) or list((state.get("row_audits") or {}).values())


def _row_text(row: dict, clause: Optional[dict] = None) -> str:
    out = f"{row['row_id']}, {row.get('particulars') or row['row_id']}: the insurer deducted {inr(row.get('insurer_amount'))}"
    if row.get("policy_amount") is not None:
        out += f"; your policy allows {inr(row['policy_amount'])}"
    out += f". Verdict: {wording_for(row)}."
    if row.get("explanation"):
        out += f" {row['explanation']}"
    if clause:
        out += f" Policy clause {clause.get('clause_id')}: \"{_excerpt(clause.get('text', ''))}\""
    return out


def _excerpt(text: str, limit: int = 320) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _match_rows(question: str, rows: list[dict]) -> list[dict]:
    q = question.lower()
    ids = {m.upper().replace("CO-PAY", "COPAY") for m in ROW_ID.findall(question)}
    hit = [r for r in rows if r["row_id"].upper() in ids]
    if hit:
        return hit
    wanted = {w for key, words in TOPICS.items() if key in q for w in words}
    return [r for r in rows if wanted and any(w in f"{r.get('particulars', '')} {r.get('kind', '')} {r['row_id']}".lower()
                                              for w in wanted)]


async def _clause_for_rule(tk: ScopedToolkit, rule_ref: str, state: dict) -> Optional[dict]:
    if not rule_ref:
        return None
    try:
        found = await tk.clauses_for_rule(rule_ref, wording_uin=(state.get("policy") or {}).get("wording_uin") or None,
                                          case_id=state.get("case_id"))
    except ClaimClearToolError:
        return None
    return (found.get("clauses") or [None])[0]


async def _search(tk: ScopedToolkit, question: str, state: dict, k: int = 2) -> list[dict]:
    try:
        found = await tk.search_clauses(question, k=k, wording_uin=(state.get("policy") or {}).get("wording_uin") or None,
                                        case_id=state.get("case_id"))
    except ClaimClearToolError:
        return []
    return found.get("hits", [])


async def rule_answer(question: str, state: dict, tk: ScopedToolkit) -> dict:
    """A grounded answer without an LLM: picks what the question is about and quotes the tools' results."""
    q = question.lower()
    audit = state.get("letter_audit") or {}
    rows = _rows(state)
    sources: list[str] = []

    clause_ids = [c.upper() for c in CLAUSE_ID.findall(question)]
    if clause_ids:
        parts = []
        for cid in clause_ids[:2]:
            try:
                c = await tk.get_clause(cid, wording_uin=(state.get("policy") or {}).get("wording_uin") or None,
                                        case_id=state.get("case_id"))
            except ClaimClearToolError:
                c = {"found": False}
            if c.get("found"):
                parts.append(f"Clause {cid} ({c.get('title', '')}): \"{_excerpt(c.get('text', ''), 600)}\"")
                sources.append(c.get("citation") or cid)
            else:
                parts.append(f"Your policy wording has no clause {cid}.")
        return {"text": " ".join(parts), "sources": sources, "how": "rules"}

    if rows:
        matched = _match_rows(question, rows)
        if matched:
            parts = []
            for r in matched[:2]:
                clause = await _clause_for_rule(tk, r.get("rule_ref", ""), state)
                if clause:
                    sources.append(clause.get("citation") or clause.get("clause_id"))
                parts.append(_row_text(r, clause))
            return {"text": "\n\n".join(parts), "sources": sources, "how": "rules"}

        if any(w in q for w in STATUS) and state.get("submission"):
            sub, st = state["submission"], state.get("grievance_status") or {}
            return {"text": f"Your grievance was filed with reference {sub['reference']}; status: {st.get('status', sub['status'])}."
                            + (" This is a dry run: nothing was sent to the insurer yet." if sub.get("dry_run") else ""),
                    "sources": [], "how": "rules"}

        if any(w in q for w in DISPUTE):
            disputable = [r for r in rows if r.get("verdict") == "does_not_match_policy" and (r.get("difference") or 0) > 0]
            amount = audit.get("disputable_amount")
            if disputable and amount:
                lines = [f"{inr(amount)} may be disputable, from {len(disputable)} deduction(s):"]
                lines += [f"• {_row_text(r)}" for r in disputable]
                sub = state.get("submission")
                if sub:
                    lines.append(f"A grievance was filed: reference {sub['reference']} ({sub['status']}).")
                elif state.get("grievance"):
                    lines.append("A grievance letter covering these rows is drafted for you to approve, edit or reject.")
                lines.append("ClaimClear can't promise the outcome: the insurer, the ombudsman or a court decides.")
                return {"text": "\n".join(lines), "sources": sources, "how": "rules"}
            if amount is not None:
                return {"text": "Nothing on this letter can be shown not to match your policy, so ClaimClear "
                                "found nothing to dispute." + (f" Overall the gap is {inr(amount)}, but no single deduction "
                                                               "is wrong under the policy." if amount else ""),
                        "sources": [], "how": "rules"}

        if any(w in q for w in TOTALS) and audit:
            text = (f"The insurer paid {inr(audit.get('insurer_paid'))}. Under your policy the amount payable is "
                    f"{inr(audit.get('policy_payable'))}.")
            if audit.get("disputable_amount"):
                text += f" {inr(audit['disputable_amount'])} may be disputable."
            if audit.get("unverified_amount"):
                text += f" {inr(audit['unverified_amount'])} can't be checked without more information."
            return {"text": text, "sources": [], "how": "rules"}

        if any(w in q for w in SUMMARY) and state.get("explanation"):
            return {"text": state["explanation"], "sources": [], "how": "rules"}

    hits = await _search(tk, question, state)
    if hits:
        parts = ["Here is what your policy wording says:"]
        for h in hits:
            parts.append(f"Clause {h['clause_id']} ({h.get('title', '')}): \"{_excerpt(h.get('text', ''))}\"")
            sources.append(h.get("citation") or h["clause_id"])
        if not rows:
            parts.append("Upload your bill, settlement letter and policy schedule to check your own deductions.")
        return {"text": "\n".join(parts), "sources": sources, "how": "rules"}
    return {"text": "I couldn't find that in your claim or your policy wording. Try naming a deduction (for example "
                    "room rent or co-pay), a row such as R1, or a clause number.", "sources": [], "how": "rules"}


def _facts(state: dict) -> dict:
    audit = state.get("letter_audit") or {}
    return {
        "insurer_paid": audit.get("insurer_paid"), "policy_payable": audit.get("policy_payable"),
        "may_be_disputable": audit.get("disputable_amount"), "cannot_be_checked": audit.get("unverified_amount"),
        "rows": [{"row": r["row_id"], "particulars": r.get("particulars"), "insurer_deducted": r.get("insurer_amount"),
                  "policy_allows": r.get("policy_amount"), "verdict": wording_for(r), "engine_reasoning": r.get("explanation")}
                 for r in _rows(state)],
        "explanation": state.get("explanation"),
        "open_questions": [q.get("text") for q in state.get("questions", [])],
        "grievance": {"drafted_for_rows": (state.get("grievance") or {}).get("row_ids"),
                      "filed": state.get("submission")} if state.get("grievance") else None,
        "policy": {k: (state.get("policy") or {}).get(k) for k in ("insurer", "product", "sum_insured", "period_start",
                                                                   "period_end")} if state.get("policy") else None,
    }
