"""Grievance agent, the approval gate, and the portal submission (the only write).

* ``grievance_agent`` drafts a grievance for the **disputable rows only**, in plain words built from the engine's
  own data: how the insurer got its figure (the matching method's title) and which bill lines it included that the
  policy excludes (set difference of line IDs: no arithmetic). The critic's checks run on it before anyone sees it.
* ``approval_gate`` is an explicit node that pauses with ``interrupt()`` and records the person's decision as its
  own step in the history: approve (with the gate's token, after an optional edit that re-hashes the text) or
  reject (``grievance_declined``).
* ``portal_submit`` files it: refuses without approval, without a token, or when the text no longer matches its
  hash; the insurer-portal server checks the hash and the HMAC token again.
"""

from __future__ import annotations

import logging

from claimclear_contracts.handoffs import GrievanceDraft
from claimclear_memory.store import MemoryStoreError
from claimclear_tools import signals
from claimclear_tools.agents import GRIEVANCE_AGENT
from claimclear_tools.results import ClaimClearToolError
from langgraph.types import interrupt

from .. import checks
from ..services import Services
from ..state import (OUTCOME_CRITIC_BLOCKED, OUTCOME_GRIEVANCE_DECLINED, OUTCOME_GRIEVANCE_FILED, OUTCOME_NO_GRIEVANCE,
                     GraphState)
from .common import sha256

log = logging.getLogger("claimclear.graph")


def basis(row: dict, settlement: dict, claim: dict) -> str:
    """Why a row doesn't match the policy, in plain words, from the engine's data only.

    The method the insurer used is the engine's own title for the matching hypothesis; the extra lines are the
    insurer's lines minus the lines the policy's deduction covers (both lists come from the engine)."""
    match = next((m for m in row.get("matches", []) if m.get("hypothesis_id") == row.get("method")), None)
    if match is None:
        return row.get("explanation", "")[:600]          # e.g. a rejection: the engine's reasoning as written
    policy_lines = {lid for d in settlement.get("deductions", []) if d.get("rule_ref") == row.get("rule_ref")
                    for lid in d.get("line_ids", [])}
    extra = [lid for lid in match.get("line_ids", []) if lid not in policy_lines] if policy_lines else []
    names = {line["line_id"]: line.get("description", line["line_id"]) for line in claim.get("lines", [])}
    text = f"How the insurer reached its figure: {match['title'].lower()}."
    if extra:
        text += (" That includes charges the policy does not allow this deduction on: "
                 f"{', '.join(names.get(l, l) for l in extra)}.")
    return text


def make(services: Services) -> dict:
    async def grievance_agent(state: GraphState) -> dict:
        letter_audit = state.get("letter_audit") or {}
        rows = signals.disputable_rows(letter_audit.get("rows", []))
        if not rows:
            return {"route": signals.NO_GRIEVANCE, "outcome": OUTCOME_NO_GRIEVANCE,
                    "trace": ["GrievanceAgent: no disputable row, nothing to draft"]}
        policy, claim, settlement = state.get("policy") or {}, state.get("claim") or {}, state.get("settlement") or {}
        lines = [f"To: The Grievance Redressal Officer, {policy.get('insurer', 'the insurer')}",
                 f"Subject: Request to review the settlement of claim {claim.get('claim_id')} "
                 f"(policy {policy.get('policy_no')})", "",
                 "I request a review of the deductions below. Checked against the policy wording "
                 f"({policy.get('wording_uin', 'on record')}), they do not match my policy:", ""]
        for i, r in enumerate(rows, start=1):
            lines.append(f"{i}. {r.get('particulars', r['row_id'])}: {checks.inr(r['insurer_amount'])} was deducted; "
                         f"under the policy the deduction is {checks.inr(r['policy_amount'])}, so "
                         f"{checks.inr(r['difference'])} more was deducted than the policy allows. "
                         f"{basis(r, settlement, claim)}")
        lines += ["", f"The amount payable under the policy is {checks.inr(letter_audit.get('policy_payable'))} and "
                      f"{checks.inr(letter_audit.get('insurer_paid'))} was paid, so "
                      f"{checks.inr(letter_audit.get('disputable_amount'))} may be disputable.",
                  "Please re-examine these deductions and share the working for each of them.", "",
                  f"Policyholder, policy {policy.get('policy_no')}"]
        text = "\n".join(lines)
        problems = checks.review_draft(text, {}, letter_audit, settlement=settlement,
                                       row_audits=(state.get("row_audits") or {}).values())
        if problems:
            return {"outcome": OUTCOME_CRITIC_BLOCKED, "route": "critic_blocked",
                    "trace": [f"GrievanceAgent: draft refused by the critic checks: {problems}"]}
        draft = GrievanceDraft.build(case_id=state["case_id"], claim_id=str(claim.get("claim_id") or state["case_id"]),
                                     row_ids=[r["row_id"] for r in rows], text=text).model_dump()
        update: dict = {"grievance": draft, "human_approved": False, "approval_token": None, "route": "awaiting_approval",
                        "trace": [f"GrievanceAgent: drafted for rows {draft['row_ids']} "
                                  f"(sha256 {draft['text_sha256'][:12]}...); waiting for the policyholder's approval"]}
        mem = services.memory_for(state.get("user_id"))
        if mem is not None:
            try:
                g = mem.open_grievance(draft["claim_id"], draft["row_ids"])
                update["memory_grievance_id"] = getattr(g, "grievance_id", None)
            except MemoryStoreError as exc:
                log.info("memory: no grievance record: %s", exc)
        return update

    async def approval_gate(state: GraphState) -> dict:
        """Pauses for the person's decision. Resumed by ``HumanApprovalGateway`` with
        ``{"decision": "approve", "approval_token", "edited_text"?}`` or ``{"decision": "reject", "reason"}``."""
        g = state["grievance"]
        decision = interrupt({"case_id": state["case_id"], "grievance": g}) or {}
        if decision.get("decision") != "approve":
            reason = decision.get("reason") or "The policyholder chose not to file a grievance."
            return {"human_approved": False, "approval_token": None, "outcome": OUTCOME_GRIEVANCE_DECLINED,
                    "route": "declined", "trace": [f"ApprovalGate: rejected: {reason}"]}
        edited = decision.get("edited_text")
        note = "approved the text unchanged"
        if edited is not None and edited != g["text"]:
            g = GrievanceDraft.build(g["case_id"], g["claim_id"], g["row_ids"], edited).model_dump()
            note = "edited the text and approved the new version"
        return {"grievance": g, "approval_token": decision.get("approval_token"), "human_approved": True,
                "route": "approved", "trace": [f"ApprovalGate: the policyholder {note} (sha256 {g['text_sha256'][:12]}...)"]}

    async def portal_submit(state: GraphState) -> dict:
        g = state.get("grievance")
        if not g:
            raise ValueError("portal submission: no grievance draft")
        if not state.get("human_approved"):
            raise PermissionError("approval gate: the policyholder has not approved this grievance")
        if sha256(g["text"]) != g["text_sha256"]:
            raise PermissionError("approval gate: the text changed after approval (SHA-256 differs)")
        token = state.get("approval_token")
        if not token:
            raise PermissionError("approval gate: no approval token")
        tk = services.tools_for(GRIEVANCE_AGENT)
        try:
            receipt = await tk.file_grievance(g["case_id"], g["claim_id"], g["row_ids"], g["text"], g["text_sha256"], token)
            status = await tk.grievance_status(receipt["reference"])
        except ClaimClearToolError as exc:
            raise PermissionError(f"insurer portal refused the filing: {exc.info.code}: {exc.info.message}") from exc
        mem = services.memory_for(state.get("user_id"))
        gid = state.get("memory_grievance_id")
        if mem is not None and gid:
            try:
                mem.update_grievance(gid, "approved", text_sha256=g["text_sha256"])
                mem.update_grievance(gid, "filed", reference_no=receipt["reference"])
            except MemoryStoreError as exc:
                log.info("memory: grievance status not updated: %s", exc)
        dry = " (dry run: nothing was sent to the insurer)" if receipt.get("dry_run") else ""
        return {"submission": receipt, "grievance_status": status, "outcome": OUTCOME_GRIEVANCE_FILED,
                "route": "filed", "trace": [f"PortalSubmit: filed as {receipt['reference']} [{receipt['status']}]{dry}"]}

    return {"grievance_agent": grievance_agent, "approval_gate": approval_gate, "portal_submit": portal_submit}
