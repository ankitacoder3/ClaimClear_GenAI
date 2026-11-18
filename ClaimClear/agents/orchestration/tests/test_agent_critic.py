"""Critic agent: the independent audit review and the draft review, every failure kind, retry/replan/stop."""

from __future__ import annotations

import copy

import pytest
from claimclear_contracts.handoffs import CriticReport
from claimclear_memory import MemoryStore

from claimclear_graph.testing import tool_error

from conftest import call, load, node_fn, run, states_before


@pytest.fixture(scope="module")
def st():
    return states_before("SET-01")


@pytest.fixture(scope="module")
def fx():
    return load("SET-01")


@pytest.fixture(scope="module")
def drafted(st):
    """The state the critic's draft review sees: the real explainer's output on the recorded state."""
    fn, _ = node_fn("explainer")
    return {**st["explainer"], **run(fn(st["explainer"]))}


def audit_with(fx, change):
    def audit(case, letter, hypothesis_ids=None):
        a = call(fx, "audit_settlement_letter")
        change(a)
        return a
    return audit


# --------------------------------------------------------------------------- audit review


def test_audit_review_passes_and_writes_a_valid_report(st):
    fn, _ = node_fn("critic")
    out = run(fn(st["critic"]))
    CriticReport.model_validate(out["critic"])
    assert out["critic"]["passed"] and out["critic_stage"] == "audit_passed"
    assert out["letter_audit"]["disputable_amount"] == 8522.86 and out["route"] == "offer_grievance"
    assert out["critic_verdict"]["confidence"] == 1.0 and out["critic_verdict"]["requires_replan"] is False


def r3_disagrees(a):
    for r in a["rows"]:
        if r["row_id"] == "R3":
            r["verdict"] = "matches_policy"


@pytest.mark.parametrize("revision,replan,target", [(0, False, "settlement_auditor"), (1, True, "supervisor"),
                                                     (2, True, "supervisor")])
def test_disagreement_retries_then_replans(st, fx, revision, replan, target):
    fn, _ = node_fn("critic", overrides={"audit_settlement_letter": audit_with(fx, r3_disagrees)})
    out = run(fn({**st["critic"], "revision_count": revision}))
    CriticReport.model_validate(out["critic"])
    assert out["critic_stage"] == "audit_failed" and out["revision_count"] == revision + 1
    assert out["critic_verdict"]["requires_replan"] is replan and out["critic_verdict"]["target_retry_node"] == target
    assert out["critic"]["attempt"] == min(revision + 1, 2)
    assert any(f["check"] == "disputable_total" for f in out["critic"]["failures"])


def test_a_row_the_auditor_skipped_is_a_disagreement(st):
    fn, _ = node_fn("critic")
    state = copy.deepcopy(st["critic"])
    del state["row_audits"]["R2"]
    out = run(fn(state))
    assert out["critic_stage"] == "audit_failed" and "R2" in out["critic_verdict"]["critique"]


def test_policy_amount_disagreement_is_caught(st, fx):
    def change(a):
        a["rows"][0]["policy_amount"] = a["rows"][0]["policy_amount"] + 1
    fn, _ = node_fn("critic", overrides={"audit_settlement_letter": audit_with(fx, change)})
    assert run(fn(st["critic"]))["critic_stage"] == "audit_failed"


def test_unfinished_rows_ask_for_a_replan_once(st, fx):
    def unverifiable(a):
        for r in a["rows"]:
            if r["row_id"] == "R3":
                r["verdict"] = "not_verifiable"
    fn, _ = node_fn("critic", overrides={"audit_settlement_letter": audit_with(fx, unverifiable)})
    state = copy.deepcopy(st["critic"])
    state["row_audits"]["R3"].update(verdict="not_verifiable", exhaustive=False)
    out = run(fn(state))                                    # both agree, but R3 was only partly tested
    assert out["critic_verdict"]["requires_replan"] is True
    assert "rows not fully tested: R3" in out["critic_verdict"]["critique"]
    after = run(fn({**state, "replan_reason": "rows not fully tested"}))
    assert after["critic_stage"] == "audit_passed"          # after one replan it doesn't loop on the same rows


def test_audit_tool_error_ends_the_run(st):
    def fail(*a, **k):
        raise tool_error("audit_settlement_letter", "POLICY_MISMATCH")
    fn, _ = node_fn("critic", overrides={"audit_settlement_letter": fail})
    out = run(fn(st["critic"]))
    assert out["outcome"] == "tool_error" and out["route"] == "fix_case_assembly"


def test_a_passed_audit_is_remembered_with_consent(st, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    store.for_user("u1").grant_consent("test")
    fn, _ = node_fn("critic", memory_store=store)
    run(fn({**st["critic"], "user_id": "u1"}))
    assert store.for_user("u1").claim("AGI/HC/2526/004512") is not None


def test_an_unsettled_audit_is_not_remembered(st, tmp_path):
    store = MemoryStore(str(tmp_path / "m.db"))
    store.for_user("u1").grant_consent("test")
    fn, _ = node_fn("critic", memory_store=store)
    state = {**st["critic"], "user_id": "u1", "settlement": {**st["critic"]["settlement"], "status": "needs_information"}}
    run(fn(state))
    assert store.for_user("u1").claims() == []


# --------------------------------------------------------------------------- draft review


def test_draft_review_passes_on_the_real_explanation(drafted):
    fn, _ = node_fn("critic")
    out = run(fn(drafted))
    assert out["critic_stage"] == "draft_passed" and out["route"] == "offer_grievance" and "outcome" not in out


def test_nothing_disputable_ends_with_no_grievance(drafted):
    fn, _ = node_fn("critic")
    la = {**drafted["letter_audit"], "disputable_amount": 0.0}
    assert run(fn({**drafted, "letter_audit": la}))["outcome"] == "no_grievance"


def test_an_unsettled_case_ends_with_needs_information(drafted):
    fn, _ = node_fn("critic")
    la = {**drafted["letter_audit"], "disputable_amount": None}
    assert run(fn({**drafted, "letter_audit": la}))["outcome"] == "needs_information"


@pytest.mark.parametrize("bad,check", [
    ("The insurer owes you ₹12,345.", "figure_not_from_engine"),
    ("You will get this money back.", "forbidden_phrase"),
    ("This is guaranteed.", "forbidden_phrase"),
])
def test_each_draft_problem_fails_the_review(drafted, bad, check):
    fn, _ = node_fn("critic")
    out = run(fn({**drafted, "explanation": drafted["explanation"] + " " + bad, "draft_attempt": 1}))
    assert out["critic_stage"] == "draft_failed" and check in {f["check"] for f in out["critic"]["failures"]}
    assert "outcome" not in out and out["revision_count"] == drafted.get("revision_count", 0) + 1


def test_wrong_verdict_wording_fails(drafted):
    fn, _ = node_fn("critic")
    draft = copy.deepcopy(drafted["draft"])
    for s in draft["sentences"]:
        if s["row_ids"] == ["R3"]:
            s["text"] = s["text"].replace("may be disputable", "matches your policy")
    out = run(fn({**drafted, "draft": draft}))
    assert "verdict_wording" in {f["check"] for f in out["critic"]["failures"]}


def test_an_invented_clause_fails(drafted):
    fn, _ = node_fn("critic")
    draft = copy.deepcopy(drafted["draft"])
    draft["sentences"][1]["clause_ids"] = ["Z.99"]
    out = run(fn({**drafted, "draft": draft}))
    assert "clause_not_found" in {f["check"] for f in out["critic"]["failures"]}


def test_second_failed_draft_is_blocked(drafted):
    fn, _ = node_fn("critic")
    out = run(fn({**drafted, "explanation": "You will get ₹1.", "draft_attempt": 2}))
    assert out["outcome"] == "critic_blocked" and out["critic"]["attempt"] == 2


def test_remembered_figures_are_allowed(drafted):
    fn, _ = node_fn("critic")
    text = drafted["explanation"] + " Last year you were paid ₹4,321."
    assert run(fn({**drafted, "explanation": text}))["critic_stage"] == "draft_failed"
    ok = run(fn({**drafted, "explanation": text, "memory": {"figures": [4321]}}))
    assert ok["critic_stage"] == "draft_passed"
