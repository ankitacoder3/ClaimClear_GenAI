"""The single-agent runner: a clear stop without a model, the report, and one development case end to end with a
scripted agent (a stand-in for the model that calls the real tools on the real servers).

    cd development/dev_eval/single_agent_dev_cases
    ../../../.venv-agents/bin/python -m pytest -q test_run.py
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run as runner  # noqa: E402


class ScriptedAgent(BaseChatModel):
    """Plays a script of tool-call turns, reporting token usage like a provider (so E1's meter counts it)."""

    script: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        step = self.script.pop(0) if self.script else []
        usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        msg = AIMessage(content="" if step else "done.", usage_metadata=usage,
                        response_metadata={"token_usage": {"prompt_tokens": 100, "completion_tokens": 20}},
                        tool_calls=[{"name": n, "args": a, "id": f"t{i}-{len(self.script)}"} for i, (n, a) in enumerate(step)])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def test_without_a_model_it_stops_with_a_clear_message(monkeypatch):
    for var in ("CLAIMCLEAR_LLM_BASE_URL", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit, match="needs a model"):
        asyncio.run(runner.main(["--only", "syn-dev-005", "--no-write"]))


def test_p95_and_report():
    assert runner.p95([]) == 0.0 and runner.p95([3.0, 1.0, 2.0]) == 3.0
    row = {"case": "syn-dev-005", "outcome": "disputable_reported", "audited": True, "error": None,
           "usage": {"model_calls": 5, "input_tokens": 500, "output_tokens": 100, "cost_usd": 0.001, "tool_calls": 9,
                     "seconds": 2.0},
           "policy_violations": ["figure no tool produced: ₹1"],
           "score": {"expected_overall": "disputable", "engine_overall": "disputable", "overall_right": True}}
    text = runner.report([row], {"syn-dev-005": {"engine_overall": "disputable"}}, "scripted")
    assert "| 1 | 1 | 1/1 |" in text and "| 1/1 |" in text            # ran, audited, overall right; same as C0
    assert "5 model calls" in text and "Policy violations: 1" in text and "figure no tool produced" in text


pytest.importorskip("langchain_mcp_adapters")


def test_one_development_case_end_to_end_with_a_scripted_agent(capsys):
    from claimclear_tools import ClaimClearToolkit, signals
    from claimclear_tools.case import build_case

    c0 = runner.c0_module()
    c0.WORK.mkdir(parents=True, exist_ok=True)
    mapping, extracted = c0.prepare()
    answer = json.loads((c0.DATASET / c0.SPLIT / "answers" / "syn-dev-005.json").read_text(encoding="utf-8"))
    case_id = c0.store_case_id("syn-dev-005", answer, mapping)     # reproducible: the runner prepares the same IDs
    ex = extracted["syn-dev-005"]

    async def case_input():
        async with ClaimClearToolkit() as tk:
            return build_case(ex["claim"], await tk.get_policy(case_id), await tk.get_claim_history(case_id))
    case = asyncio.run(case_input())
    text = "R3 was cut by ₹30,371.43; your policy allows ₹21,400. In total ₹8,522.86 may be disputable."
    agent = ScriptedAgent(script=[
        [("list_case_documents", {"case_id": case_id})],
        [("expected_settlement", {"case": case})],
        [("reproduce_deduction", {"case": case, "letter": ex["letter"], "row_id": r})
         for r in signals.rows_to_audit(ex["letter"])],
        [("audit_settlement_letter", {"case": case, "letter": ex["letter"]})],
        [("submit_review", {"explanation": text, "overall_verdict": "disputable"})]])

    assert asyncio.run(runner.main(["--only", "syn-dev-005", "--no-write"], llm=agent)) == 0
    out = capsys.readouterr().out
    assert "syn-dev-005" in out and "disputable_reported" in out
    assert "| 1 | 1 | 1/1 |" in out                                   # ran, produced an audit, overall verdict right
    assert "5 model calls" in out and "Policy violations: 0" in out
