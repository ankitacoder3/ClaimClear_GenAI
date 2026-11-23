"""Tests for the fixes made after the code review (Guide 2, Part E: F2, F3, F7, F8, F10, F11)."""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import ToolMessage

from claimclear_graph import HumanApprovalGateway, Services, build_claimclear_graph, initial_state, open_checkpointer
from claimclear_graph.hooks import is_error_message
from claimclear_graph.testing import ReplayToolkit, tool_error

from conftest import Case, load, run


def _result(fx, method):
    return next(c["result"] for c in fx["calls"] if c["key"].startswith(f'["{method}"'))


# --------------------------------------------------------------------------- F2: no document text in the state


def test_document_text_is_not_checkpointed_only_a_summary():
    c = Case("SET-01")
    run(c.start())

    async def history():
        return [h async for h in c.graph.aget_state_history(c.cfg)]
    for snap in run(history()):                                       # no checkpoint holds page text
        assert "pages" not in snap.values
    summary = run(c.values())["page_summary"]
    assert len(summary) == 4 and all(s["pages_returned"] == 1 and s["unreadable_pages"] == [] for s in summary.values())
    assert "Private room" not in json.dumps(run(c.values())["page_summary"])


# --------------------------------------------------------------------------- F3: independent calls run concurrently


def test_row_audits_run_concurrently_and_keep_order():
    fx = load("SET-01")
    rows = {json.loads(c["key"])[1][2]: c["result"] for c in fx["calls"] if c["key"].startswith('["reproduce_deduction"')}
    running, peak = 0, 0

    async def slow(case, letter, row_id, hypothesis_ids=None):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return json.loads(json.dumps(rows[row_id]))
    state = run(Case("SET-01", overrides={"reproduce_deduction": slow}).start())
    assert peak == 4                                                  # R1, R2, R3, COPAY at once
    assert list(state["row_audits"]) == ["R1", "R2", "R3", "COPAY"]


# --------------------------------------------------------------------------- F7: retries for retryable errors


def test_retryable_error_is_retried_then_succeeds():
    fx = load("SET-01")
    calls = {"n": 0}

    def flaky(case):
        calls["n"] += 1
        if calls["n"] == 1:
            err = tool_error("expected_settlement", "UPSTREAM_UNAVAILABLE", "provider down")
            raise err
        return _result(fx, "expected_settlement")
    c = Case("SET-01", overrides={"expected_settlement": flaky}, retry_backoff=0.01)
    run(c.start())
    assert calls["n"] == 2 and run(c.gate.is_paused_for_approval(c.cfg))


def test_non_retryable_error_is_not_retried_and_retries_are_bounded():
    counts = {"bad": 0, "down": 0}

    def invalid(case):
        counts["bad"] += 1
        raise tool_error("expected_settlement", "INVALID_ARGUMENTS")
    state = run(Case("SET-01", overrides={"expected_settlement": invalid}, retry_backoff=0.01).start())
    assert counts["bad"] == 1 and state["outcome"] == "invalid_extraction"

    def down(case):
        counts["down"] += 1
        raise tool_error("expected_settlement", "UPSTREAM_UNAVAILABLE")
    state = run(Case("SET-01", overrides={"expected_settlement": down}, retry_backoff=0.01, retry_attempts=2).start())
    assert counts["down"] == 3 and state["outcome"] == "tool_error" and state["route"] == "retry_later"


# --------------------------------------------------------------------------- F8: plain language / other languages


def test_rewriter_output_is_what_the_user_reads_and_is_checked():
    async def plain(text, language):
        return "In short: " + text.replace("Checked against your policy", "Going by your policy")
    c = Case("SET-01", rewriter=plain, language="en")
    state = run(c.start())
    assert state["explanation"].startswith("In short: ") and "Going by your policy" in state["explanation"]
    assert state["critic"]["passed"] and run(c.gate.is_paused_for_approval(c.cfg))
    assert "rewritten (en)" in "\n".join(state["trace"])


def test_rewriter_that_changes_a_figure_is_caught_and_the_plain_table_shown():
    async def sloppy(text, language):
        return text.replace("₹8,522.86", "₹8,523")                   # "rounded": not a tool's figure
    state = run(Case("SET-01", rewriter=sloppy, language="hi").start())
    trace = "\n".join(state["trace"])
    assert "draft attempt 1 FAILED" in trace and "₹8523" in trace
    assert "plain verdict table (fallback)" in trace and "draft attempt 2 passed" in trace
    assert "₹8,523" not in state["explanation"]


def test_rewriter_failure_falls_back_to_the_source_text():
    async def broken(text, language):
        raise RuntimeError("model unavailable")
    state = run(Case("SET-02", rewriter=broken).start())
    assert state["outcome"] == "no_grievance" and "rewrite failed" in "\n".join(state["trace"])


# --------------------------------------------------------------------------- F10: error detection in the audit log


def test_error_detection_uses_status_first():
    assert is_error_message(ToolMessage(content="ok", tool_call_id="1", status="error"))
    assert is_error_message(ToolMessage(content="fine", tool_call_id="1", artifact={"isError": True}))
    assert is_error_message(ToolMessage(content='Error executing tool x: {"code": "A"}', tool_call_id="1"))
    assert not is_error_message(ToolMessage(content='{"ok": true}', tool_call_id="1"))


# --------------------------------------------------------------------------- F11: durable checkpoints


def test_paused_case_survives_a_restart_with_sqlite(tmp_path):
    fx = load("SET-01")
    url = f"sqlite:///{tmp_path / 'checkpoints.db'}"
    cfg = {"configurable": {"thread_id": "restart-test"}}

    async def before_restart():
        async with open_checkpointer(url) as saver:
            graph = build_claimclear_graph(Services(toolkit=ReplayToolkit(fx["calls"])), checkpointer=saver)
            await graph.ainvoke(initial_state(fx["case_id"], claim=fx["claim"], letter=fx["letter"]), cfg)
            return await HumanApprovalGateway(graph).is_paused_for_approval(cfg)

    async def after_restart():                                       # a new process: new graph, same database
        async with open_checkpointer(url) as saver:
            graph = build_claimclear_graph(Services(toolkit=ReplayToolkit(fx["calls"])), checkpointer=saver)
            gate = HumanApprovalGateway(graph)
            assert await gate.is_paused_for_approval(cfg)
            return await gate.approve_and_resume(cfg)
    assert run(before_restart())
    final = run(after_restart())
    assert final["outcome"] == "grievance_filed" and final["submission"]["reference"].startswith("DRYRUN-")


def test_open_checkpointer_rejects_unknown_urls():
    async def go():
        async with open_checkpointer("redis://x"):
            pass
    with pytest.raises(ValueError):
        run(go())


# --------------------------------------------------------------------------- F5: evaluating the LLM extraction


def _eval_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "development" / "dev_eval" / "graph_dev_cases" / "run.py"
    spec = importlib.util.spec_from_file_location("graph_dev_cases_run", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_runs_the_graph_on_the_extractor_and_scores_the_extraction():
    ev, fx = _eval_module(), load("SET-01")
    want = {"claim": fx["claim"], "letter": fx["letter"]}
    seen = {}

    async def good(toolkit, case_id, documents, pages):              # a perfect extraction
        seen["pages"] = sorted(pages)                                 # the extractor gets the text, the state doesn't
        return json.loads(json.dumps(want))

    res = run(ev.run_one(ReplayToolkit(fx["calls"]), fx["case_id"], want, "llm-good", good))
    st = res["state"]
    assert res["grievance_offered"] and st["outcome"] == "grievance_declined"
    assert "claim extracted" in "\n".join(st["trace"]) and len(seen["pages"]) == 4
    assert ev.compare_extraction({"claim": st["claim"], "letter": st["letter"]}, want)["all_right"]

    bad = json.loads(json.dumps(want))
    bad["letter"]["rows"] = bad["letter"]["rows"][:2]                 # the model missed row R3
    verdict = ev.compare_extraction(bad, want)
    assert verdict["letter_rows"] is False and verdict["all_right"] is False and verdict["bill_total"] is True
    assert ev.compare_extraction(None, want) == {"extracted": False}
