"""Supervisor agent: the first plan, replans, loop counters and memory loading."""

from __future__ import annotations

import pytest
from claimclear_contracts.handoffs import Plan
from claimclear_memory import MemoryStore

from conftest import node_fn, run, states_before


@pytest.fixture(scope="module")
def before():
    return states_before("SET-01")["supervisor"]


def test_first_plan_and_defaults(before):
    fn, _ = node_fn("supervisor")
    out = run(fn(before))
    Plan.model_validate(out["plan"])                                   # a valid contract plan
    assert out["plan"]["version"] == 1 and len(out["plan"]["steps"]) == 7
    assert (out["revision_count"], out["max_revisions"], out["draft_attempt"]) == (0, 3, 0)
    assert out["route"] == "start" and out["human_approved"] is False
    assert out["trace"] == ["Supervisor: plan v1 with 7 steps (memory off)"]


def test_max_revisions_from_state_wins_over_services(before):
    fn, _ = node_fn("supervisor", max_revisions=5)
    assert run(fn({**before, "max_revisions": 1}))["max_revisions"] == 1
    assert run(fn(before))["max_revisions"] == 5


def test_existing_revision_count_is_kept(before):
    fn, _ = node_fn("supervisor")
    assert run(fn({**before, "revision_count": 2}))["revision_count"] == 2


def test_replan_bumps_the_version_and_routes_to_the_auditor(before):
    fn, _ = node_fn("supervisor")
    state = {**before, "plan": run(fn(before))["plan"], "row_audits": {"R1": {}, "R3": {}},
             "critic_verdict": {"requires_replan": True, "critique": "R3 disagreed twice", "passed": False}}
    out = run(fn(state))
    Plan.model_validate(out["plan"])
    assert out["plan"]["version"] == 2 and out["plan"]["replan_reason"] == "R3 disagreed twice"
    assert out["replan_rows"] == ["R1", "R3"] and out["route"] == "replan"
    assert out["critic_verdict"]["requires_replan"] is False            # consumed: no replan loop
    again = run(fn({**state, "plan": out["plan"]}))
    assert again["plan"]["version"] == 3


def test_replan_without_a_critique_or_previous_plan(before):
    fn, _ = node_fn("supervisor")
    out = run(fn({**before, "critic_verdict": {"requires_replan": True}}))
    assert out["plan"]["version"] == 2 and out["plan"]["replan_reason"] == "critic asked"
    assert "every row" in out["plan"]["steps"][0]["goal"]              # no row audits yet


def test_very_long_critique_is_truncated_for_the_contract(before):
    fn, _ = node_fn("supervisor")
    out = run(fn({**before, "critic_verdict": {"requires_replan": True, "critique": "x" * 2000}}))
    assert len(out["plan"]["replan_reason"]) == 300


def test_memory_with_consent_is_loaded(before, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    store.for_user("u1").grant_consent("test")
    fn, _ = node_fn("supervisor", memory_store=store)
    out = run(fn({**before, "user_id": "u1"}))
    assert "memory" in out and "memory: 0 remembered claim(s)" in out["trace"][0]


def test_memory_without_consent_or_user(before, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    fn, _ = node_fn("supervisor", memory_store=store)
    out = run(fn({**before, "user_id": "u_no_consent"}))
    assert not out["memory"].get("enabled", False) and "memory: no consent" in out["trace"][0]
    assert "memory off" in run(fn(before))["trace"][0]                   # no user_id at all
