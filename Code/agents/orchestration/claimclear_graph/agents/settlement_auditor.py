"""Settlement auditor (and the ``ask_user`` pause): what the policy allows, then every letter row reproduced.

Tools: ``expected_settlement``, ``reproduce_deduction`` (one call per row, run concurrently; a row tested only
partly is re-tested with every hypothesis). When the engine needs information it can use, the auditor routes to
``ask_user``, which pauses the graph with ``interrupt()`` and applies the answers with
``claimclear_tools.apply_answer``; an unanswered question is never asked again, so the loop always ends.
"""

from __future__ import annotations

from claimclear_tools import apply_answer, signals
from claimclear_tools.agents import SETTLEMENT_AUDITOR
from claimclear_tools.results import ClaimClearToolError
from langgraph.types import interrupt

from .. import checks
from ..services import Services
from ..state import OUTCOME_INVALID_EXTRACTION, OUTCOME_TOOL_ERROR, STAGE_AUDIT_PENDING, GraphState, engine_case
from .common import ANSWERABLE, gather_calls, stop


def make(services: Services) -> dict:
    async def settlement_auditor(state: GraphState) -> dict:
        tk = services.tools_for(SETTLEMENT_AUDITOR)
        case, letter = engine_case(state), state["letter"]
        answers = state.get("answers") or {}
        try:
            settlement = await tk.expected_settlement(case)
        except ClaimClearToolError as exc:
            outcome = OUTCOME_INVALID_EXTRACTION if exc.info.code == "INVALID_ARGUMENTS" else OUTCOME_TOOL_ERROR
            return stop(exc, "SettlementAuditor", outcome)
        if signals.after_settlement(settlement) == signals.ASK_USER:
            ask = [q for q in signals.questions_to_ask(settlement)
                   if q["question_id"] in ANSWERABLE and q["question_id"] not in answers]
            first = signals.rows_to_audit(letter)[:1]
            if ask and first:
                # Ask only what the letter's audit still needs. The engine settles some questions from the letter
                # itself: a rejection the bill's own inconsistencies confirm (a discharge before the admission: asking
                # to "correct" those dates helps no one), or a claim the insurer paid with no waiting-period row (its
                # letter has accepted the condition as covered). The first row's audit says which questions remain.
                try:
                    probe = await tk.reproduce_deduction(case, letter, first[0])
                except ClaimClearToolError:
                    probe = None
                if probe is not None:
                    still = {q.get("question_id") for q in probe.get("questions", [])}
                    ask = [q for q in ask if q["question_id"] in still]
            if ask:
                return {"settlement": settlement, "questions": ask, "route": signals.ASK_USER,
                        "trace": [f"SettlementAuditor: the engine needs answers first: "
                                  f"{', '.join(q['question_id'] for q in ask)}"]}

        async def audit(row_id: str):
            try:
                row = await tk.reproduce_deduction(case, letter, row_id)
                if signals.after_row_audit(row) == signals.REPLAN:     # partial test: re-test every method
                    return row_id, await tk.reproduce_deduction(case, letter, row_id), True
                return row_id, row, False
            except ClaimClearToolError as exc:
                if exc.info.code == "ROW_NOT_FOUND":
                    return row_id, None, False
                raise

        try:
            results = await gather_calls(audit(r) for r in signals.rows_to_audit(letter))
        except ClaimClearToolError as exc:
            return stop(exc, "SettlementAuditor")
        rows = {row_id: row for row_id, row, _ in results if row is not None}
        replanned = [row_id for row_id, row, again in results if again]
        questions = signals.questions_to_ask(settlement, rows.values())
        disputable = signals.disputable_rows(rows.values())
        verdicts = ", ".join(f"{k} {v['verdict']}" for k, v in rows.items())
        return {"settlement": settlement, "row_audits": rows, "questions": questions, "replan_rows": [],
                "critic_stage": STAGE_AUDIT_PENDING, "route": signals.AUDIT_ROWS,
                "trace": [f"SettlementAuditor: policy payable {checks.inr(settlement.get('payable_amount'))} "
                          f"[{settlement['status']}]; rows: {verdicts}; {len(disputable)} disputable row(s)"
                          + (f"; re-tested {replanned}" if replanned else "")]}

    async def ask_user(state: GraphState) -> dict:
        questions = [q for q in state.get("questions", []) if q["question_id"] in ANSWERABLE]
        reply = interrupt({"case_id": state["case_id"], "questions": questions}) or {}
        claim, answers, notes = state["claim"], dict(state.get("answers") or {}), []
        for q in questions:
            qid = q["question_id"]
            answers[qid] = reply.get(qid)                      # None = not answered: never asked again
            if reply.get(qid) is None:
                notes.append(f"{qid} unanswered")
                continue
            try:
                claim = apply_answer(claim, q, reply[qid], state.get("settlement"))
                notes.append(f"{qid}={reply[qid]!r}")
            except ValueError as exc:
                answers[qid] = None
                notes.append(f"{qid} rejected ({exc})")
        return {"claim": claim, "answers": answers, "route": "answered",
                "trace": [f"AskUser: {'; '.join(notes) or 'no questions'}"]}

    return {"settlement_auditor": settlement_auditor, "ask_user": ask_user}
