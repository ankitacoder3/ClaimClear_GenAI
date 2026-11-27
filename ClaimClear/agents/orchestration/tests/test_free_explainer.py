"""Signature 2 ablation (E4): the free-form explainer switch. No model: a fake one records the prompt."""
from __future__ import annotations

import asyncio

from claimclear_graph import free_explainer


class FakeLLM:
    def __init__(self):
        self.prompt = ""

    async def ainvoke(self, prompt):
        self.prompt = prompt
        return type("Msg", (), {"content": "You were paid less than your policy allows; you may raise a grievance."})()


def test_the_switch_defaults_to_fact_bound(monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_EXPLAINER", raising=False)
    assert free_explainer.mode() == "fact_bound"
    monkeypatch.setenv("CLAIMCLEAR_EXPLAINER", "free")
    assert free_explainer.mode() == "free"


def test_one_model_call_from_the_audit_and_clauses():
    llm = FakeLLM()
    audit = {"insurer_paid": 100, "policy_payable": 150, "disputable_amount": 50,
             "rows": [{"row_id": "R1", "particulars": "Room rent", "insurer_amount": 50, "policy_amount": 0,
                       "verdict": "does_not_match_policy", "secret": "not sent"}]}
    text = asyncio.run(free_explainer.llm_free_explainer(llm)(audit, [{"clause_id": "4.1", "text": "Room rent cap"}]))
    assert text.startswith("You were paid less")
    assert "Room rent" in llm.prompt and "4.1: Room rent cap" in llm.prompt and "not sent" not in llm.prompt
