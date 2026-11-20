"""How the review's findings are shown in the chat, from Member 3's verified explainer draft (display only).

The explainer writes one sentence per letter row plus summary sentences (``state["draft"]["sentences"]``). The rows
are already in the verdict table, so their sentences go into a folded "Row by row" step; the rest become short
bullets, without repeats; the disclaimer closes the message in italics. The text of every sentence is the
critic-checked text, unchanged.
"""
from __future__ import annotations

from claimclear_contracts.verdicts import wording_for
from claimclear_graph.checks import inr


def render(state: dict) -> tuple[str, list[str]]:
    """``(message, row_lines)``: the findings message (Markdown) and the row-by-row sentences for a folded step."""
    audit = state.get("letter_audit") or {}
    totals = f"**Insurer paid** {inr(audit.get('insurer_paid'))} · **Your policy allows** {inr(audit.get('policy_payable'))}"
    if audit.get("disputable_amount"):
        totals += f" · **May be disputable** {inr(audit.get('disputable_amount'))}"
    table = "| Row | Deduction | Insurer | Policy | Verdict |\n|---|---|---|---|---|\n" + "\n".join(
        f"| {r['row_id']} | {(r.get('particulars') or '').replace('|', '/')} | {inr(r.get('insurer_amount'))} | "
        f"{inr(r.get('policy_amount'))} | {wording_for(r)} |" for r in audit.get("rows", []))
    sentences = (state.get("draft") or {}).get("sentences") or []
    if not sentences:                                        # no draft (e.g. a fallback): the explanation as written
        return f"### What I found\n{totals}\n\n{table}\n\n{state.get('explanation', '')}", []
    rows, summary, seen = [], [], set()
    for s in sentences:
        text = (s.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        if s.get("row_ids"):
            rows.append(text)
        elif "F-PAYABLE" not in (s.get("fact_ids") or []):  # paid / payable is already in the totals line
            summary.append(text)
    disclaimer = summary.pop() if summary else ""            # the explainer always ends with the disclaimer
    bullets = "\n".join(f"- {t}" for t in summary)
    message = f"### What I found\n{totals}\n\n{table}\n\n" + (f"**In short**\n{bullets}\n\n" if bullets else "") + \
        (f"_{disclaimer}_" if disclaimer else "")
    return message.rstrip(), rows
