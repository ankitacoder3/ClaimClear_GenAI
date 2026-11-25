"""Explainer agent: sentences and table, clause citations, every totals case, notes, fallback, rewriter."""

from __future__ import annotations

import copy

import pytest
from claimclear_contracts.handoffs import ExplainerDraft

from claimclear_graph.testing import tool_error

from conftest import node_fn, run, states_before


@pytest.fixture(scope="module")
def before():
    return states_before("SET-01")["explainer"]


def text(out):
    return out["explanation"]


def test_full_explanation_is_a_valid_contract_draft(before):
    fn, tk = node_fn("explainer")
    out = run(fn(before))
    ExplainerDraft.model_validate(out["draft"])
    assert out["draft_attempt"] == 1 and out["critic_stage"] == "draft_ready"
    rows = [s for s in out["draft"]["sentences"] if s["row_ids"]]
    assert [s["row_ids"][0] for s in rows] == ["R1", "R2", "R3", "COPAY"]
    assert "₹8,522.86 may be disputable" in text(out) and "(see " in text(out)
    assert tk.log.count("clauses_for_rule") == 4                       # one per rule, not per row
    assert out["audit_table_markdown"].count("\n") == 5                 # header + rule + 4 rows


def test_citations_are_clauses_that_were_returned(before):
    fn, _ = node_fn("explainer")
    out = run(fn(before))
    cited = {c for s in out["draft"]["sentences"] for c in s["clause_ids"]}
    assert cited and cited <= set(out["clauses"])


def test_second_attempt_is_the_plain_table(before):
    fn, _ = node_fn("explainer")
    out = run(fn({**before, "draft_attempt": 1}))
    assert out["draft_attempt"] == 2 and "(see " not in text(out) and "Note:" not in text(out)
    assert "plain verdict table (fallback)" in out["trace"][0]


@pytest.mark.parametrize("code", ["NO_RULE_MAP", "INDEX_UNAVAILABLE", "UNKNOWN_RULE"])
def test_missing_clauses_mean_no_citation_not_an_error(before, code):
    def fail(*a, **k):
        raise tool_error("clauses_for_rule", code)
    fn, _ = node_fn("explainer", overrides={"clauses_for_rule": fail})
    out = run(fn(before))
    assert "(see " not in text(out) and out["critic_stage"] == "draft_ready" and "0 rule(s) cited" in out["trace"][0]


def audit(before, **change):
    la = copy.deepcopy(before["letter_audit"])
    la.update(change)
    return {**before, "letter_audit": la}


def test_nothing_disputable(before):
    fn, _ = node_fn("explainer")
    assert "Nothing on this letter looks disputable" in text(run(fn(audit(before, disputable_amount=0.0))))


def test_a_gap_without_a_disputable_row(before):
    la = copy.deepcopy(before["letter_audit"])
    for r in la["rows"]:
        r["verdict"], r["difference"] = "matches_policy", 0.0
    fn, _ = node_fn("explainer")
    out = run(fn({**before, "letter_audit": {**la, "disputable_amount": 0.5}}))
    assert "no single deduction on the letter can be shown" in text(out) and "drafts a grievance" not in text(out)


def test_unverified_amounts_are_mentioned(before):
    fn, _ = node_fn("explainer")
    assert "can't be checked without more information" in text(run(fn(audit(before, unverified_amount=6000.0))))


def test_no_payable_amount_skips_the_opening_sentence(before):
    fn, _ = node_fn("explainer")
    assert not text(run(fn(audit(before, policy_payable=None)))).startswith("The insurer paid")


def test_row_without_a_policy_amount(before):
    la = copy.deepcopy(before["letter_audit"])
    la["rows"][0].update(policy_amount=None, verdict="not_verifiable")
    fn, _ = node_fn("explainer")
    out = run(fn({**before, "letter_audit": la}))
    first = next(s for s in out["draft"]["sentences"] if s["row_ids"] == ["R1"])["text"]
    assert "your policy allows" not in first and "we can't check this" in first


def test_open_questions_and_missing_wording_are_noted(before):
    fn, _ = node_fn("explainer")
    out = run(fn({**before, "questions": [{"question_id": "Q-TIE-X", "text": "Was it a planned admission?"}],
                  "wording": {**before["wording"], "wording_needed": True}}))
    assert "Still open: Was it a planned admission?" in text(out) and "Your policy wording isn't on file" in text(out)


def test_answered_questions_are_not_repeated(before):
    fn, _ = node_fn("explainer")
    out = run(fn({**before, "questions": [{"question_id": "Q-EYE", "text": "Which eye?"}], "answers": {"Q-EYE": "left"}}))
    assert "Which eye?" not in text(out)


def test_pipes_in_particulars_do_not_break_the_table(before):
    la = copy.deepcopy(before["letter_audit"])
    la["rows"][0]["particulars"] = "Room | rent"
    fn, _ = node_fn("explainer")
    table = run(fn({**before, "letter_audit": la}))["audit_table_markdown"]
    assert "Room / rent" in table and all(line.count("|") == 7 for line in table.splitlines())


def test_very_long_particulars_fit_the_contract(before):
    la = copy.deepcopy(before["letter_audit"])
    la["rows"][0]["particulars"] = "x" * 5000
    fn, _ = node_fn("explainer")
    ExplainerDraft.model_validate(run(fn({**before, "letter_audit": la}))["draft"])   # max 600 chars per sentence


def test_rewriter_output_is_shown_and_the_source_kept(before):
    async def rewrite(t, lang):
        return f"[{lang}] {t}"
    fn, _ = node_fn("explainer", rewriter=rewrite, language="hi")
    out = run(fn(before))
    assert text(out).startswith("[hi] ") and not out["draft"]["sentences"][0]["text"].startswith("[hi]")
    assert "rewritten (hi)" in out["trace"][0]


def test_rewriter_failure_keeps_the_source_text(before):
    async def rewrite(t, lang):
        raise TimeoutError("model down")
    fn, _ = node_fn("explainer", rewriter=rewrite)
    out = run(fn(before))
    assert text(out) == ExplainerDraft.model_validate(out["draft"]).text and "rewrite failed" in out["trace"][0]


def test_the_plain_table_is_never_rewritten(before):
    async def rewrite(t, lang):
        return "REWRITTEN"
    fn, _ = node_fn("explainer", rewriter=rewrite)
    assert text(run(fn({**before, "draft_attempt": 1}))) != "REWRITTEN"


def _with_integrity(before, definite=True):
    fact = {"fact_id": "F-INTEGRITY-ROOM-DAYS-EXCEED-STAY", "kind": "integrity", "rule_ref": "fraud",
            "text": "The bill is inconsistent: the bill charges 13 room and ICU days for a 3-night stay",
            "amount": None, "formula": "", "line_ids": ["L01"], "inputs": {"code": "room_days_exceed_stay",
                                                                         "definite": definite}}
    settlement = {**before["settlement"], "facts": list(before["settlement"]["facts"]) + [fact]}
    return {**before, "settlement": settlement}


def test_a_definite_inconsistency_on_the_bill_is_mentioned(before):
    fn, _ = node_fn("explainer")
    out = run(fn(_with_integrity(before)))
    assert "13 room and ICU days for a 3-night stay" in text(out) and "insurer may question" in text(out)
    assert any(s["fact_ids"] == ["F-INTEGRITY-ROOM-DAYS-EXCEED-STAY"] for s in out["draft"]["sentences"])


def test_a_weak_finding_is_not_mentioned(before):
    fn, _ = node_fn("explainer")
    assert "insurer may question" not in text(run(fn(_with_integrity(before, definite=False))))


def test_an_assumption_from_the_letter_is_stated(before):
    fact = {"fact_id": "F-CONDITION-FROM-LETTER", "kind": "assumption", "rule_ref": "listed_illness_waiting_period",
            "text": "The insurer paid this claim with no waiting-period deduction, so its letter treats the condition "
                    "as covered (listed illness short); the deductions are checked on that basis",
            "amount": None, "formula": "", "line_ids": [], "inputs": {"condition_type": "listed_illness_short"}}
    audit = {**before["letter_audit"], "settlement": {**(before["letter_audit"].get("settlement") or {}),
                                                      "facts": [fact]}}
    fn, _ = node_fn("explainer")
    out = run(fn({**before, "letter_audit": audit}))
    assert "treats the condition as covered" in text(out)


def test_another_products_wording_is_never_cited(before):
    fn, tk = node_fn("explainer")
    out = run(fn({**before, "wording": {**before["wording"], "cite_clauses": False, "wording_needed": True,
                                        "status": "other_product"}}))
    assert tk.log.count("clauses_for_rule") == 0
    assert not any(s["clause_ids"] for s in out["draft"]["sentences"]) and "(see " not in text(out)
    assert "doesn't have your policy's wording, so no clause is quoted" in text(out)
    assert "Your policy wording isn't on file" not in text(out)          # said once, not twice
    assert all(line.split("|")[-2].strip() in ("-", "Policy clause", "---")
               for line in out["audit_table_markdown"].splitlines())
