"""Signature 2 ablation (E4): the free-form explainer, the baseline the fact-bound explainer is compared with.

Signature 2 in our brief, "Explain without overclaiming": ON (the default) is the fact-bound explainer
(``agents/explainer.py``: every sentence tied to an engine fact or a clause, every ₹ figure checked by the critic).
OFF is this module: one model call writes the answer directly from the audit and the retrieved clauses, with no
sentence links, and the critic does not enforce its figure checks (it only counts what it would have flagged).

    CLAIMCLEAR_EXPLAINER=fact_bound   (default) Signature 2 ON
    CLAIMCLEAR_EXPLAINER=free         Signature 2 OFF (needs a chat model)
"""
from __future__ import annotations

import json
import os
from typing import Any

PROMPT = """You explain a health-insurance claim settlement check to an Indian policyholder with no insurance
knowledge. Write a short, plain answer (under 200 words) covering what happened, why each deduction was or was not
right, how much may be disputable, and what they can do next (and by when, if you know). Use the audit and the
policy clauses below.

<audit>
{audit}
</audit>

<clauses>
{clauses}
</clauses>"""


def mode() -> str:
    """``free`` or ``fact_bound`` (default)."""
    return "free" if os.environ.get("CLAIMCLEAR_EXPLAINER", "").strip().lower() == "free" else "fact_bound"


def llm_free_explainer(llm: Any):
    """``async (letter_audit, clauses) -> text`` from any LangChain chat model."""

    async def explain(letter_audit: dict, clauses: list[dict]) -> str:
        audit = {k: letter_audit.get(k) for k in ("insurer_paid", "policy_payable", "disputable_amount",
                                                  "unverified_amount")}
        audit["rows"] = [{k: r.get(k) for k in ("row_id", "particulars", "insurer_amount", "policy_amount", "verdict")}
                         for r in letter_audit.get("rows", [])]
        text = "\n\n".join(f"{c.get('clause_id', '')}: {(c.get('text') or '')[:800]}" for c in clauses[:8])
        msg = await llm.ainvoke(PROMPT.format(audit=json.dumps(audit, ensure_ascii=False, default=str), clauses=text))
        out = getattr(msg, "content", msg)
        if isinstance(out, list):
            out = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out)
        return str(out).strip()

    return explain
