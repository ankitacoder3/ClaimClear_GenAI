"""Policy analyst: the policy schedule, its wording, earlier claims, and candidate clauses per letter row.

Tools: ``get_policy_wording``, ``get_policy``, ``get_claim_history``, ``search_clauses`` (one search per letter
row, run concurrently). Ends the run when no policy is on record (ask the user for it) or when the bill, the
schedule and the history name different policies. A policy number printed with look-alike characters is
replaced by the schedule's and flagged.
"""

from __future__ import annotations

from claimclear_tools import build_case, signals
from claimclear_tools.agents import POLICY_ANALYST
from claimclear_tools.results import ClaimClearToolError

from .. import checks
from ..services import Services
from ..state import OUTCOME_ASK_FOR_POLICY, OUTCOME_POLICY_MISMATCH, OUTCOME_TOOL_ERROR, GraphState
from .common import gather_calls, lookalike_policy_no, stop


def make(services: Services) -> dict:
    async def policy_analyst(state: GraphState) -> dict:
        tk = services.tools_for(POLICY_ANALYST)
        case_id = state["case_id"]
        try:
            wording, policy, history = await gather_calls(
                [tk.get_policy_wording(case_id), tk.get_policy(case_id), tk.get_claim_history(case_id)])
        except ClaimClearToolError as exc:
            outcome = OUTCOME_ASK_FOR_POLICY if exc.info.code == "POLICY_NOT_FOUND" else OUTCOME_TOOL_ERROR
            return stop(exc, "PolicyAnalyst", outcome)
        mem = services.memory_for(state.get("user_id"))
        if mem is not None:
            from claimclear_memory import merge_history
            history = merge_history(history, mem.claim_history(policy["policy_no"]) or [])
            mem.remember_policy(policy, wording_uin=wording.get("wording_uin", ""))
        claim, flags, note = state["claim"], list(state.get("security_flags", [])), ""
        printed = claim.get("policy_no", "")
        if printed != policy["policy_no"] and lookalike_policy_no(printed, policy["policy_no"]):
            # Look-alike characters (Cyrillic А, Ѕ ...) in the printed number: a parser attack. Use the schedule's
            # number from get_policy and raise a guardrail flag, as Member 2's evaluation run does.
            claim = {**claim, "policy_no": policy["policy_no"]}
            flags.append("lookalike policy number on the bill (schedule's number used)")
            note = "; look-alike policy number replaced and flagged"
        try:
            build_case(claim, policy, history)                    # the three must name the same policy
        except ValueError as exc:
            return {"policy": policy, "wording": wording, "history": history, "outcome": OUTCOME_POLICY_MISMATCH,
                    "route": "policy_mismatch", "trace": [f"PolicyAnalyst: {exc}"]}
        clauses: dict = dict(state.get("clauses") or {})
        queries = [q for q in (f"{r.get('particulars', '')} {r.get('reason', '')}".strip()
                               for r in state["letter"].get("rows", [])) if q]
        try:
            found = await gather_calls(tk.search_clauses(q, k=2, wording_uin=wording.get("wording_uin") or None,
                                                         case_id=case_id) for q in queries)
            for result in found:
                for hit in result.get("hits", []):
                    clauses.setdefault(hit["clause_id"], hit)
        except ClaimClearToolError as exc:
            note += f"; search unavailable ({exc.info.code} -> {exc.info.action})"
        wn = " (ask the user for their wording)" if wording.get("wording_needed") else ""
        return {"policy": policy, "wording": wording, "history": history, "clauses": clauses, "route": signals.OK,
                "claim": claim, "security_flags": sorted(set(flags)),
                "trace": [f"PolicyAnalyst: policy {policy['policy_no']}, sum insured {checks.inr(policy['sum_insured'])}, "
                          f"wording {wording.get('wording_uin')} [{wording.get('status')}]{wn}, "
                          f"{len(history)} earlier claim(s), {len(clauses)} candidate clause(s){note}"]}

    return {"policy_analyst": policy_analyst}
