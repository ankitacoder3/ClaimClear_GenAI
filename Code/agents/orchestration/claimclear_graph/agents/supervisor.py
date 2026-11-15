"""Supervisor: plans the run, loads memory, replans when the critic loses confidence.

Tools: none (``AGENT_TOOLS["supervisor"]`` is empty). Reads ``critic_verdict`` and ``user_id``; writes ``plan``,
``memory`` and the loop counters. A replan routes straight back to the settlement auditor (see ``router``).
"""

from __future__ import annotations

from ..plan import first_plan, replan
from ..services import Services
from ..state import GraphState


def make(services: Services) -> dict:
    async def supervisor(state: GraphState) -> dict:
        verdict = state.get("critic_verdict") or {}
        if verdict.get("requires_replan"):
            rows = list(state.get("row_audits", {}))
            new_plan = replan(state.get("plan") or {"version": 1}, verdict.get("critique", "critic asked"), rows)
            return {"plan": new_plan, "replan_reason": new_plan["replan_reason"], "replan_rows": rows,
                    "critic_verdict": {**verdict, "requires_replan": False}, "route": "replan",
                    "trace": [f"Supervisor: replan v{new_plan['version']}: {new_plan['replan_reason']}"]}
        update: dict = {"plan": first_plan(), "revision_count": state.get("revision_count", 0),
                        "max_revisions": state.get("max_revisions", services.max_revisions), "draft_attempt": 0,
                        "route": "start", "human_approved": False}
        note = "memory off"
        mem = services.memory_for(state.get("user_id"))
        if mem is not None:
            ctx = mem.context()
            update["memory"] = ctx
            enabled = bool(ctx) and ctx.get("enabled", True)    # without consent memory says enabled: False
            note = f"memory: {len(ctx.get('claims', []))} remembered claim(s)" if enabled else "memory: no consent"
        update["trace"] = [f"Supervisor: plan v1 with {len(update['plan']['steps'])} steps ({note})"]
        return update

    return {"supervisor": supervisor}
