"""Critic: two independent reviews, both deterministic.

Tools: ``audit_settlement_letter``.

* **Audit review** (after the auditor, ``critic_stage == audit_pending``): re-runs the whole letter independently;
  every auditor row must agree. 1st failure: retry the auditor; 2nd: ask the supervisor to replan; the router's
  loop guard stops it at ``max_revisions``. A passed audit is remembered (memory, with consent).
* **Draft review** (after the explainer, ``critic_stage == draft_ready``): every ₹ figure from a tool, allowed
  wording per verdict, no forbidden phrase, only real clauses. The text checked is what the user will read,
  i.e. the rewritten explanation when a rewriter is configured. 1st failure: plain table; 2nd: ``critic_blocked``.
"""

from __future__ import annotations

import logging

from claimclear_contracts.handoffs import CriticReport
from claimclear_memory.store import MemoryStoreError
from claimclear_tools import signals
from claimclear_tools.agents import CRITIC
from claimclear_tools.results import ClaimClearToolError

from .. import checks
from ..services import Services
from ..state import (OUTCOME_CRITIC_BLOCKED, OUTCOME_NEEDS_INFORMATION, OUTCOME_NO_GRIEVANCE, STAGE_AUDIT_FAILED,
                     STAGE_AUDIT_PASSED, STAGE_DRAFT_FAILED, STAGE_DRAFT_PASSED, STAGE_DRAFT_READY, GraphState,
                     engine_case)
from .common import stop

log = logging.getLogger("claimclear.graph")


def make(services: Services) -> dict:
    async def critic(state: GraphState) -> dict:
        if state.get("critic_stage") == STAGE_DRAFT_READY:
            return review_draft(state)
        return await review_audit(state)

    async def review_audit(state: GraphState) -> dict:
        tk = services.tools_for(CRITIC)
        case = engine_case(state)
        try:
            letter_audit = await tk.audit_settlement_letter(case, state["letter"])
        except ClaimClearToolError as exc:
            return stop(exc, "Critic")
        revision = state.get("revision_count", 0)
        failures = checks.review_audit(state.get("row_audits", {}), letter_audit)
        unfinished = checks.unfinished_rows(state.get("row_audits", {}))
        conf = checks.confidence(letter_audit)
        disputable = letter_audit.get("disputable_amount")
        if failures or (unfinished and not state.get("replan_reason")):
            replan = revision >= 1 or (not failures and bool(unfinished))
            critique = "; ".join(f["detail"] for f in failures) or f"rows not fully tested: {', '.join(unfinished)}"
            report = CriticReport(passed=False, attempt=min(revision + 1, 2),
                                  failures=failures or [checks.failure("disputable_total", critique)],
                                  disputable_amount=disputable).model_dump(mode="json")
            return {"letter_audit": letter_audit, "critic": report, "critic_stage": STAGE_AUDIT_FAILED,
                    "revision_count": revision + 1, "route": "critic_failed",
                    "critic_verdict": {"passed": False, "confidence": conf, "critique": critique,
                                       "requires_replan": replan,
                                       "target_retry_node": "supervisor" if replan else "settlement_auditor"},
                    "trace": [f"Critic: audit review #{revision + 1} FAILED -> "
                              f"{'replan' if replan else 'auditor retry'}: {critique[:200]}"]}
        mem = services.memory_for(state.get("user_id"))
        if mem is not None and (state.get("settlement") or {}).get("status") != "needs_information":
            try:
                mem.remember_claim(case, letter_audit, case_id=state["case_id"], letter=state["letter"])
            except MemoryStoreError as exc:
                log.info("memory refused the audit: %s", exc)
        report = CriticReport(passed=True, attempt=1, disputable_amount=disputable).model_dump(mode="json")
        return {"letter_audit": letter_audit, "critic": report, "critic_stage": STAGE_AUDIT_PASSED,
                "route": signals.after_letter_audit(letter_audit),
                "critic_verdict": {"passed": True, "confidence": conf, "requires_replan": False,
                                   "target_retry_node": None,
                                   "critique": "every row agrees with the independent letter audit"},
                "trace": [f"Critic: audit verified independently (confidence {conf:.0%}); policy payable "
                          f"{checks.inr(letter_audit.get('policy_payable'))}, insurer paid "
                          f"{checks.inr(letter_audit.get('insurer_paid'))}, may be disputable {checks.inr(disputable)}"]}

    def review_draft(state: GraphState) -> dict:
        draft = state.get("draft") or {}
        letter_audit = state.get("letter_audit") or {}
        text = (state.get("explanation") or "") + "\n" + (state.get("audit_table_markdown") or "")
        row_sentences = {s["row_ids"][0]: s["text"] for s in draft.get("sentences", []) if len(s.get("row_ids", [])) == 1}
        cited = {c for s in draft.get("sentences", []) for c in s.get("clause_ids", [])}
        failures = checks.review_draft(
            text, row_sentences, letter_audit, settlement=state.get("settlement"),
            row_audits=(state.get("row_audits") or {}).values(), cited_clause_ids=cited,
            known_clause_ids=(state.get("clauses") or {}).keys(),
            remembered=(state.get("memory") or {}).get("figures", []))
        attempt = max(1, min(state.get("draft_attempt", 1), 2))
        if state.get("explainer_mode") == "free":            # Signature 2 OFF: counted, not enforced (E4 ablation)
            route = signals.after_letter_audit(letter_audit)
            done = {}
            if route == signals.NO_GRIEVANCE:
                done = {"outcome": OUTCOME_NO_GRIEVANCE if letter_audit.get("disputable_amount") is not None
                        else OUTCOME_NEEDS_INFORMATION}
            report = CriticReport(passed=True, attempt=attempt,
                                  disputable_amount=letter_audit.get("disputable_amount")).model_dump(mode="json")
            return {"critic": report, "critic_stage": STAGE_DRAFT_PASSED, "route": route, **done,
                    "trace": [f"Critic: free-form explanation (Signature 2 OFF): {len(failures)} issue(s) not enforced"
                              + (f": {'; '.join(f['detail'] for f in failures)[:200]}" if failures else "")]}
        report = CriticReport(passed=not failures, attempt=attempt, failures=failures,
                              disputable_amount=letter_audit.get("disputable_amount")).model_dump(mode="json")
        if not failures:
            route = signals.after_letter_audit(letter_audit)
            done = {}
            if route == signals.NO_GRIEVANCE:
                settled = letter_audit.get("disputable_amount") is not None
                done = {"outcome": OUTCOME_NO_GRIEVANCE if settled else OUTCOME_NEEDS_INFORMATION}
            return {"critic": report, "critic_stage": STAGE_DRAFT_PASSED, "route": route, **done,
                    "trace": [f"Critic: draft attempt {attempt} passed (figures, wording, clauses) -> {route}"]}
        update = {"critic": report, "critic_stage": STAGE_DRAFT_FAILED, "route": "draft_failed",
                  "revision_count": state.get("revision_count", 0) + 1,
                  "trace": [f"Critic: draft attempt {attempt} FAILED: "
                            f"{'; '.join(f['detail'] for f in failures)[:240]}"]}
        if attempt >= 2:
            update["outcome"] = OUTCOME_CRITIC_BLOCKED
        return update

    return {"critic": critic}
