"""C0, the fixed workflow: the review's steps in a fixed order, with no agent decisions.

    read the documents (one fixed extraction prompt) -> policy, wording, history -> expected settlement and every
    letter row -> the letter audit -> a templated explanation -> done

It reuses the specialists' step functions, so the tools and the extraction prompt are exactly C2's, and leaves out
everything that decides: no supervisor or plan, no critic (the audit is taken as the engine returns it, the
explanation is shown unchecked), no retries or replanning, no grievance step. A step that fails ends the run with
that outcome. The engine's questions get "don't know" (the same rule the harness applies to C2).
"""

from __future__ import annotations

from typing import Any, Iterable

from claimclear_tools import ClaimClearToolError, signals
from claimclear_tools.agents import CRITIC

from claimclear_graph.agents import make_nodes
from claimclear_graph.services import Services
from claimclear_graph.state import OUTCOME_NEEDS_INFORMATION, OUTCOME_NO_GRIEVANCE, OUTCOME_TOOL_ERROR, engine_case

OUTCOME_DISPUTABLE = "disputable_reported"       # C0 reports what may be disputable; it has no grievance step


async def run_fixed(toolkit: Any, llm: Any, case_id: str, *, flags: Iterable[str] = (), extractor=None,
                    budget=None, usage=None) -> dict:
    services = Services(toolkit=toolkit, extractor=extractor, retry_attempts=0)
    nodes = make_nodes(services)
    state: dict = {"case_id": case_id, "trace": [], "questions_asked": [], "grievance_offered": False}
    if flags:
        state["security_flags"] = list(flags)

    def apply(update: dict) -> None:
        for k, v in update.items():
            state[k] = state.get(k, []) + list(v) if k == "trace" else v

    for step in ("document_reader", "policy_analyst"):
        apply(await nodes[step](state))
        if state.get("outcome"):
            return state

    for _ in range(3):                                   # the engine's questions: "don't know", then audit again
        apply(await nodes["settlement_auditor"](state))
        if state.get("outcome"):
            return state
        if state.get("route") != signals.ASK_USER:
            break
        state["questions_asked"] += [q.get("text", q["question_id"]) for q in state.get("questions", [])]
        state["answers"] = {**(state.get("answers") or {}), **{q["question_id"]: None for q in state["questions"]}}

    try:
        state["letter_audit"] = await services.tools_for(CRITIC).audit_settlement_letter(engine_case(state),
                                                                                           state["letter"])
    except ClaimClearToolError as exc:
        state.update(outcome=OUTCOME_TOOL_ERROR, trace=state["trace"] + [f"C0: audit failed: {exc.info.code}"])
        return state
    apply(await nodes["explainer"](state))

    if (state.get("settlement") or {}).get("status") == "needs_information":
        state["outcome"] = OUTCOME_NEEDS_INFORMATION
    elif signals.after_letter_audit(state["letter_audit"]) == signals.OFFER_GRIEVANCE:
        state["outcome"] = OUTCOME_DISPUTABLE
    else:
        state["outcome"] = OUTCOME_NO_GRIEVANCE
    state["trace"] = state["trace"] + [f"C0: fixed workflow finished: {state['outcome']}"]
    return state
