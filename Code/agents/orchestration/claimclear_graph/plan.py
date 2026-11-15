"""The supervisor's visible plan, as Member 2's contract ``claimclear_contracts.Plan``.

The plan is shown to the user. A replan bumps ``version`` and must say why (the contract refuses a
replan without ``replan_reason``).
"""

from __future__ import annotations

from claimclear_contracts.handoffs import Plan, PlanStep

BASE_STEPS: tuple[tuple[str, str], ...] = (
    ("document_reader", "Read every uploaded document and extract the bill and the settlement letter"),
    ("policy_analyst", "Load the policy schedule, its wording and earlier claims; find the relevant clauses"),
    ("settlement_auditor", "Work out what the policy allows and test how the insurer reached each deduction"),
    ("critic", "Re-check every figure independently against the settlement engine"),
    ("explainer", "Explain each deduction in plain language with its policy clause"),
    ("critic", "Check the explanation: tool figures only, allowed wording, real clauses"),
    ("grievance_agent", "Draft a grievance for disputable rows only, for your approval"),
)


def first_plan() -> dict:
    steps = [PlanStep(step_id=f"S{i}", agent=a, goal=g) for i, (a, g) in enumerate(BASE_STEPS, start=1)]
    return Plan(version=1, steps=steps).model_dump()


def replan(previous: dict, reason: str, rows: list[str]) -> dict:
    """A new version of the plan: re-audit ``rows`` with every hypothesis, then review again."""
    what = f"rows {', '.join(rows)}" if rows else "every row"
    steps = [
        PlanStep(step_id="S1", agent="settlement_auditor", goal=f"Re-test {what} with every calculation method"),
        PlanStep(step_id="S2", agent="critic", goal="Re-check the new audit independently"),
        PlanStep(step_id="S3", agent="explainer", goal="Explain the verified result"),
        PlanStep(step_id="S4", agent="critic", goal="Check the explanation"),
        PlanStep(step_id="S5", agent="grievance_agent", goal="Draft a grievance only if something may be disputable"),
    ]
    return Plan(version=int(previous.get("version", 1)) + 1, steps=steps, replan_reason=reason[:300]).model_dump()
