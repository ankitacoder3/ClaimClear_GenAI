"""Explainer: plain-language explanation of the critic-verified audit, every row with its policy clause.

Tools: ``clauses_for_rule`` (one call per engine rule, run concurrently).

Writes ``draft`` (contract ``ExplainerDraft``: every sentence tied to its facts, rows and clauses), ``explanation``
(what the user reads) and ``audit_table_markdown``. Attempt 2 (after the critic rejected attempt 1) is the plain
verdict table only.

**Plain language and other languages.** With ``Services(rewriter=..., language="hi")`` the draft is rewritten
(e.g. into simpler English or Hindi) by ``language.llm_rewriter`` or any async ``(text, language) -> text``.
The rewrite is what the critic checks: every ₹ figure must still be a tool's figure, so a rewriter that changes,
drops into words, or invents an amount is caught, and the plain table is shown instead. The English sentences
stay in ``draft`` as the source of truth.
"""

from __future__ import annotations

import asyncio
import logging

from claimclear_contracts.handoffs import ExplainerDraft, ExplanationSentence
from claimclear_contracts.verdicts import wording_for
from claimclear_tools import signals
from claimclear_tools.agents import EXPLAINER
from claimclear_tools.results import ClaimClearToolError

from .. import checks
from ..services import Services
from ..state import STAGE_DRAFT_READY, GraphState
from .common import DISCLAIMER, cite

log = logging.getLogger("claimclear.graph")


def make(services: Services) -> dict:
    async def explainer(state: GraphState) -> dict:
        tk = services.tools_for(EXPLAINER)
        attempt = state.get("draft_attempt", 0) + 1
        letter_audit = state.get("letter_audit") or {}
        policy = state.get("policy") or {}
        clauses = dict(state.get("clauses") or {})

        refs = sorted({r["rule_ref"] for r in letter_audit.get("rows", []) if r.get("rule_ref")})

        async def lookup(ref: str):
            try:
                return ref, await tk.clauses_for_rule(ref, wording_uin=policy.get("wording_uin") or None,
                                                      case_id=state.get("case_id"))
            except ClaimClearToolError:
                return ref, {}                                   # NO_RULE_MAP / INDEX_UNAVAILABLE: no citation
        rule_clause: dict[str, dict] = {}
        for ref, found in await asyncio.gather(*(lookup(r) for r in refs)):
            if found.get("clauses"):
                rule_clause[ref] = found["clauses"][0]
                clauses.setdefault(found["clauses"][0]["clause_id"], found["clauses"][0])

        sentences: list[ExplanationSentence] = []
        paid, payable = letter_audit.get("insurer_paid"), letter_audit.get("policy_payable")
        disputable, unverified = letter_audit.get("disputable_amount"), letter_audit.get("unverified_amount")
        if payable is not None:
            sentences.append(ExplanationSentence(
                text=f"The insurer paid {checks.inr(paid)}. Checked against your policy, the amount payable "
                     f"works out to {checks.inr(payable)}.", fact_ids=["F-PAYABLE"]))
        table = ["| Row | Particulars | Insurer deducted | Policy allows | Verdict | Policy clause |",
                 "|---|---|---|---|---|---|"]
        for row in letter_audit.get("rows", []):
            clause = rule_clause.get(row.get("rule_ref") or "")
            wording = wording_for(row)
            part = (row.get("particulars") or row["row_id"])[:200]
            allowed_txt = "" if row.get("policy_amount") is None else \
                f"; your policy allows {checks.inr(row['policy_amount'])}"
            c = f" (see {cite(clause)})" if clause and attempt == 1 else ""
            sentences.append(ExplanationSentence(
                text=f"{row['row_id']}, {part}: the insurer deducted {checks.inr(row.get('insurer_amount'))}"
                     f"{allowed_txt}. Verdict: {wording}{c}.",
                row_ids=[row["row_id"]], clause_ids=[clause["clause_id"]] if c else []))
            table.append(f"| {row['row_id']} | {part.replace('|', '/')} | {checks.inr(row.get('insurer_amount'))} | "
                         f"{checks.inr(row.get('policy_amount'))} | {wording} | "
                         f"{clause['clause_id'] if clause else '-'} |")
        if disputable and disputable > 0 and signals.disputable_rows(letter_audit.get("rows", [])):
            sentences.append(ExplanationSentence(text=f"In total, {checks.inr(disputable)} may be disputable. If you "
                                                      "approve, ClaimClear drafts a grievance for these rows only."))
        elif disputable and disputable > 0:
            sentences.append(ExplanationSentence(text=f"Overall the insurer paid {checks.inr(disputable)} less than the "
                                                      "policy amount, but no single deduction on the letter can be shown "
                                                      "not to match your policy, so no grievance is drafted."))
        else:
            sentences.append(ExplanationSentence(text="Nothing on this letter looks disputable under your policy."))
        if unverified and unverified > 0:
            sentences.append(ExplanationSentence(text=f"{checks.inr(unverified)} can't be checked without more "
                                                      "information from the insurer."))
        if attempt == 1:
            for note in letter_audit.get("policy_deductions_not_on_letter", [])[:3]:
                sentences.append(ExplanationSentence(text=f"Note: your policy also allows a deduction the letter "
                                                          f"doesn't show: {note[:400]}."))
            open_q = [q for q in state.get("questions", []) if q["question_id"] not in (state.get("answers") or {})]
            for q in open_q[:3]:
                sentences.append(ExplanationSentence(text=f"Still open: {q.get('text', q['question_id'])[:500]}"))
            if (state.get("wording") or {}).get("wording_needed"):
                sentences.append(ExplanationSentence(text="Your policy wording isn't on file yet; uploading it "
                                                          "lets ClaimClear cite your exact clauses."))
        sentences.append(ExplanationSentence(text=DISCLAIMER))
        draft = ExplainerDraft(sentences=sentences)

        explanation, mode = draft.text, "full explanation" if attempt == 1 else "plain verdict table (fallback)"
        if attempt == 1 and services.rewriter is not None:
            try:
                explanation = await services.rewriter(draft.text, services.language)
                mode += f", rewritten ({services.language})"
            except Exception as exc:                            # a failed rewrite falls back to the source text
                log.warning("rewriter failed: %s", exc)
                mode += ", rewrite failed: source text used"
        return {"draft": draft.model_dump(), "explanation": explanation, "audit_table_markdown": "\n".join(table),
                "clauses": clauses, "draft_attempt": attempt, "critic_stage": STAGE_DRAFT_READY, "route": "draft_ready",
                "trace": [f"Explainer: {mode}, {len(sentences)} sentences, {len(rule_clause)} rule(s) cited"]}

    return {"explainer": explainer}
