"""Policy analyst agent: policy, wording, history, memory, look-alikes, mismatches, clause search, tool errors."""

from __future__ import annotations

import pytest
from claimclear_memory import MemoryStore

from claimclear_graph.testing import tool_error

from conftest import call, load, node_fn, run, states_before


@pytest.fixture(scope="module")
def before():
    return states_before("SET-01")["policy_analyst"]


@pytest.fixture(scope="module")
def fx():
    return load("SET-01")


def test_loads_policy_wording_history_and_clauses(before):
    fn, tk = node_fn("policy_analyst")
    out = run(fn(before))
    assert out["policy"]["policy_no"] == "AS-2025-100478" and out["wording"]["wording_uin"] == "GODHLIP24179V022324"
    assert out["history"] == [] and out["route"] == "ok" and len(out["clauses"]) >= 1
    assert tk.log.count("search_clauses") == len(before["letter"]["rows"])   # one search per letter row
    assert "sum insured ₹300,000" in out["trace"][0]


@pytest.mark.parametrize("method", ["get_policy", "get_policy_wording", "get_claim_history"])
def test_missing_policy_asks_the_user(before, method):
    def fail(*a, **k):
        raise tool_error(method, "POLICY_NOT_FOUND")
    fn, _ = node_fn("policy_analyst", overrides={method: fail})
    out = run(fn(before))
    assert out["outcome"] == "ask_user_for_policy" and out["route"] == "ask_user_to_confirm_policy"


def test_other_errors_end_as_tool_error(before):
    def fail(*a, **k):
        raise tool_error("get_policy", "CASE_NOT_FOUND")
    fn, _ = node_fn("policy_analyst", overrides={"get_policy": fail})
    assert run(fn(before))["outcome"] == "tool_error"


@pytest.mark.parametrize("printed", ["АЅ-2025-100478", "AS‐2025‐100478", "АS-2025-100478"])
def test_lookalike_policy_numbers_are_replaced_and_flagged(before, printed):
    fn, _ = node_fn("policy_analyst")
    out = run(fn({**before, "claim": {**before["claim"], "policy_no": printed}}))
    # Unicode dashes count as look-alikes too (the engine's own table maps them to "-")
    assert out["claim"]["policy_no"] == "AS-2025-100478" and out["route"] == "ok"
    assert any("lookalike" in f for f in out["security_flags"]) and "replaced and flagged" in out["trace"][0]


def test_a_different_policy_is_a_mismatch_not_a_lookalike(before):
    fn, _ = node_fn("policy_analyst")
    out = run(fn({**before, "claim": {**before["claim"], "policy_no": "AS-2025-999999"}}))
    assert out["outcome"] == "policy_mismatch" and "AS-2025-999999" in out["trace"][0]


def test_history_on_another_policy_is_a_mismatch(before, fx):
    other = [{"claim_id": "X1", "policy_no": "ZZ-1", "admission": "2025-08-01", "discharge": "2025-08-02",
              "paid_amount": 1000.0, "diagnosis": "", "procedure": "", "lines": []}]
    fn, _ = node_fn("policy_analyst", overrides={"get_claim_history": lambda *a, **k: other})
    assert run(fn(before))["outcome"] == "policy_mismatch"


@pytest.mark.parametrize("code", ["INDEX_UNAVAILABLE", "NO_RULE_MAP"])
def test_clause_search_outage_is_not_fatal(before, code):
    def fail(*a, **k):
        raise tool_error("search_clauses", code)
    fn, _ = node_fn("policy_analyst", overrides={"search_clauses": fail})
    out = run(fn(before))
    assert out["route"] == "ok" and out["clauses"] == {} and f"search unavailable ({code}" in out["trace"][0]


def test_rows_without_text_are_not_searched(before):
    letter = {**before["letter"], "rows": [{**r, "particulars": "", "reason": ""} for r in before["letter"]["rows"]]}
    fn, tk = node_fn("policy_analyst")
    out = run(fn({**before, "letter": letter}))
    assert "search_clauses" not in tk.log and out["route"] == "ok"


def test_existing_clauses_are_kept_and_hits_deduplicated(before, fx):
    hit = {"clause_id": "C.1", "text": "room rent", "citation": "x"}
    fn, _ = node_fn("policy_analyst", overrides={"search_clauses": lambda *a, **k: {"hits": [hit, hit]}})
    out = run(fn({**before, "clauses": {"Z.9": {"clause_id": "Z.9"}}}))
    assert set(out["clauses"]) == {"Z.9", "C.1"}


def test_wording_needed_is_reported(before, fx):
    wording = {**call(fx, "get_policy_wording"), "wording_needed": True, "status": "not_reviewed"}
    fn, _ = node_fn("policy_analyst", overrides={"get_policy_wording": lambda c: wording})
    assert "ask the user for their wording" in run(fn(before))["trace"][0]


def test_memory_history_is_merged_and_the_policy_remembered(before, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    store.for_user("u1").grant_consent("test")
    fn, _ = node_fn("policy_analyst", memory_store=store)
    out = run(fn({**before, "user_id": "u1"}))
    assert out["route"] == "ok"
    assert store.for_user("u1").profile("AS-2025-100478") is not None    # remembered for next time
