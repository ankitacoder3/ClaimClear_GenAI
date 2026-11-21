"""LLM smoke test (on demand): one simple case goes through the UI path and the judge must say "pass".

Needs the five servers and OPENROUTER_API_KEY, and costs about $0.02 a run, so it is off unless
CLAIMCLEAR_LLM_SMOKE=1 (CI runs it only from the "Run workflow" button):

    cd ClaimClear
    CLAIMCLEAR_LLM_SMOKE=1 .venv-agents/Scripts/python -m pytest tests/smoke/test_judge.py -s

The case is RT-N-004 (one co-pay error, no attack); CLAIMCLEAR_SMOKE_CASE picks another.
"""
from __future__ import annotations

import asyncio
import os

import pytest

import answers
import app
import ui_judge_eval

pytestmark = [pytest.mark.llm,
              pytest.mark.skipif(os.environ.get("CLAIMCLEAR_LLM_SMOKE") != "1",
                                 reason="set CLAIMCLEAR_LLM_SMOKE=1 (servers up, OpenRouter key; ~$0.02)")]
CASE = os.environ.get("CLAIMCLEAR_SMOKE_CASE", "RT-N-004")


def test_a_simple_case_passes_the_judge(monkeypatch):
    monkeypatch.setattr(app, "APP", {})                      # the real toolkit, model and review graph
    expected = answers.find(CASE)

    async def run():
        ready = await app.ready()
        try:
            return await ui_judge_eval.evaluate(ready, expected, use_judge=True)
        finally:
            await ready["cm"].__aexit__(None, None, None)
    result = asyncio.run(run())
    print(result.get("judge"), result.get("checks"))
    assert not result.get("error"), result.get("error")
    assert result["checks"]["payable_ok"] and result["checks"]["verdict_ok"], result["checks"]
    assert result["judge"]["verdict"] == "pass", result["judge"]
