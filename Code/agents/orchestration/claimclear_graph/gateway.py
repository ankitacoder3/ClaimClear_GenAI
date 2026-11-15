"""The human approval gateway: answer questions, inspect, edit, approve or reject, resume.

The graph has two pauses, both made with LangGraph's ``interrupt()`` and resumed here:

* ``ask_user``: the engine's questions; ``answer_questions(cfg, {question_id: answer})``.
* ``approval_gate``: a grievance is drafted. Only a person, through this gateway, can let it go on:

  * ``approve_and_resume`` issues the **approval token** for the exact text's SHA-256 and resumes. With
    ``CLAIMCLEAR_GATE_SECRET`` set, the token is ``HMAC-SHA256(secret, text_sha256)``, the formula the
    insurer-portal server checks; without a secret the server only checks that a token is present (development).
  * An **edit** is sent with the approval; the gate node builds a fresh ``GrievanceDraft`` (new SHA-256) and the
    token is issued for that new hash, so consent is bound to the text actually filed.
  * ``reject`` resumes the gate with a rejection: the run ends with ``grievance_declined``, recorded as the gate's
    own step in the history, and nothing is filed.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Optional

from langgraph.types import Command


def issue_token(text_sha256: str, secret: Optional[str] = None) -> str:
    """The approval token for a text hash: HMAC-SHA256 with the gate secret, else a development token."""
    secret = secret if secret is not None else os.environ.get("CLAIMCLEAR_GATE_SECRET", "")
    if secret:
        return hmac.new(secret.encode("utf-8"), text_sha256.encode("utf-8"), "sha256").hexdigest()
    return f"dev-approval-{text_sha256[:32]}"


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class HumanApprovalGateway:
    """Drives one compiled ClaimClear graph through its two kinds of pause."""

    def __init__(self, graph: Any, gate_secret: Optional[str] = None):
        self.graph = graph
        self.gate_secret = gate_secret

    # ------------------------------------------------------------------ inspection
    async def snapshot(self, config: dict):
        return await self.graph.aget_state(config)

    async def _interrupts(self, config: dict) -> list[dict]:
        snap = await self.snapshot(config)
        return [it.value or {} for task in (snap.tasks or ()) for it in (getattr(task, "interrupts", ()) or ())]

    async def is_paused_for_approval(self, config: dict) -> bool:
        """Waiting at the approval gate (its interrupt is pending, or it is the next step after a state update)."""
        snap = await self.snapshot(config)
        return "approval_gate" in (snap.next or ()) or any("grievance" in v for v in await self._interrupts(config))

    async def pending_questions(self, config: dict) -> list[dict]:
        """The engine's questions the graph is waiting on (empty when it isn't waiting)."""
        return [q for v in await self._interrupts(config) for q in v.get("questions", [])]

    async def get_pending_grievance(self, config: dict) -> tuple[Optional[str], Optional[str]]:
        """``(text, text_sha256)`` of the draft waiting for approval."""
        g = (await self.snapshot(config)).values.get("grievance") or {}
        return g.get("text"), g.get("text_sha256")

    # ------------------------------------------------------------------ decisions
    async def answer_questions(self, config: dict, answers: dict[str, Any]) -> dict:
        """Resume an ``ask_user`` pause with ``{question_id: answer}`` (see ``claimclear_tools.apply_answer``).

        Questions missing from ``answers`` count as skipped (``None``): an empty dict skips them all. (LangGraph
        would read an empty resume dict as "nothing to resume" and leave the case stuck at the question.)"""
        pending = {q["question_id"]: None for q in await self.pending_questions(config)}
        return await self.graph.ainvoke(Command(resume={**pending, **(answers or {})}), config)

    async def approve_and_resume(self, config: dict, edited_text: Optional[str] = None) -> dict:
        """Approve the draft (optionally edited first), issue the token for the final text, and resume."""
        if not await self.is_paused_for_approval(config):
            raise RuntimeError("the graph is not waiting for approval")
        text, _ = await self.get_pending_grievance(config)
        final = edited_text if edited_text is not None else text
        decision = {"decision": "approve", "approval_token": issue_token(text_sha256(final), self.gate_secret)}
        if edited_text is not None:
            decision["edited_text"] = edited_text
        return await self.graph.ainvoke(Command(resume=decision), config)

    async def reject(self, config: dict, reason: str = "The policyholder chose not to file a grievance.") -> dict:
        """Decline: the gate records the decision and the run ends without filing."""
        if not await self.is_paused_for_approval(config):
            raise RuntimeError("the graph is not waiting for approval")
        return await self.graph.ainvoke(Command(resume={"decision": "reject", "reason": reason}), config)
