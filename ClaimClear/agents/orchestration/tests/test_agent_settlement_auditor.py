"""Settlement auditor agent and the ask_user pause: engine questions, partial tests, missing rows, tool errors."""

from __future__ import annotations

import json

import pytest

from claimclear_graph.testing import tool_error

from conftest import Case, call, load, node_fn, run, states_before


@pytest.fixture(scope="module")
def before():
    return states_before("SET-01")["settlement_auditor"]


@pytest.fixture(scope="module")
def fx():
    return load("SET-01")


def rows(fx):
    return {json.loads(c["key"])[1][2]: c["result"] for c in fx["calls"] if c["key"].startswith('["reproduce_deduction"')}


def test_audits_every_row_including_copay(before):
    fn, tk = node_fn("settlement_auditor")
    out = run(fn(before))
    assert list(out["row_audits"]) == ["R1", "R2", "R3", "COPAY"]
    assert out["critic_stage"] == "audit_pending" and out["route"] == "audit_rows"
    assert out["settlement"]["payable_amount"] == 95617.5 and "1 disputable row(s)" in out["trace"][0]
    assert tk.log.count("reproduce_deduction") == 4


def test_impossible_claim_goes_back_to_the_reader(before):
    def bad(case):
        raise tool_error("expected_settlement", "INVALID_ARGUMENTS", "lines: at least one line is required")
    fn, _ = node_fn("settlement_auditor", overrides={"expected_settlement": bad})
    out = run(fn(before))
    assert out["outcome"] == "invalid_extraction" and out["route"] == "send_back_to_document_reader"


def test_engine_outage_is_a_tool_error(before):
    def bad(case):
        raise tool_error("expected_settlement", "CASE_NOT_FOUND")
    fn, _ = node_fn("settlement_auditor", overrides={"expected_settlement": bad})
    assert run(fn(before))["outcome"] == "tool_error"


def needs(fx, qid):
    s = call(fx, "expected_settlement")
    s["status"] = "needs_information"
    s["questions"] = [{"question_id": qid, "text": f"question {qid}", "options": [], "line_ids": []}]
    return lambda case: json.loads(json.dumps(s))


def asking(fx, qid):
    """Overrides for an engine that can't settle ``qid`` from the letter: the settlement and the row audits both
    carry the question (the auditor asks only what the letter's audit still needs)."""
    q = [{"question_id": qid, "text": f"question {qid}", "options": [], "line_ids": []}]
    row = {**call(fx, "reproduce_deduction"), "verdict": "not_verifiable", "questions": q}
    return {"expected_settlement": needs(fx, qid), "reproduce_deduction": lambda *a, **k: json.loads(json.dumps(row))}


def test_answerable_question_pauses_for_the_user(before, fx):
    fn, tk = node_fn("settlement_auditor", overrides=asking(fx, "Q-CONDITION-TYPE"))
    out = run(fn(before))
    assert out["route"] == "ask_user" and [q["question_id"] for q in out["questions"]] == ["Q-CONDITION-TYPE"]
    assert "row_audits" not in out                                     # rows wait for the answer (one probe only)


def test_a_question_the_letter_settles_is_not_asked(before, fx):
    # e.g. SET-32 (syn-dev-017): which waiting-period list? The insurer paid the claim, so the engine audits the
    # letter on the insurer's own acceptance and the row audits carry no question: nothing is asked.
    fn, _ = node_fn("settlement_auditor", overrides={"expected_settlement": needs(fx, "Q-CONDITION-TYPE")})
    out = run(fn(before))
    assert out["route"] == "audit_rows" and list(out["row_audits"]) == ["R1", "R2", "R3", "COPAY"]


def _rejection(before):
    letter = {**before["letter"], "letter_type": "rejection", "rows": [], "copay_amount": None,
              "rejection_reason": "The hospital could not confirm the admission; the claim is not genuine."}
    return {**before, "letter": letter}


def test_a_rejection_the_bill_confirms_is_not_held_up_by_a_question(before, fx):
    # e.g. SET-09: discharge before admission, rejected as not genuine. The engine asks for the real dates, but the
    # REJECTION row is already confirmed by the bill, so the policyholder isn't asked to "correct" them.
    confirmed = {"row_id": "REJECTION", "verdict": "matches_policy", "method": "not_genuine_documents",
                 "difference": 0.0, "questions": []}
    fn, tk = node_fn("settlement_auditor", overrides={"expected_settlement": needs(fx, "Q-ADMISSION"),
                                                      "reproduce_deduction": lambda *a, **k: dict(confirmed)})
    out = run(fn(_rejection(before)))
    assert out["route"] == "audit_rows" and out["row_audits"]["REJECTION"]["verdict"] == "matches_policy"


def test_an_unconfirmed_rejection_still_asks(before, fx):
    open_row = {"row_id": "REJECTION", "verdict": "not_verifiable", "difference": 0.0,
                "questions": [{"question_id": "Q-ADMISSION", "text": "dates?", "options": [], "line_ids": []}]}
    fn, _ = node_fn("settlement_auditor", overrides={"expected_settlement": needs(fx, "Q-ADMISSION"),
                                                     "reproduce_deduction": lambda *a, **k: dict(open_row)})
    assert run(fn(_rejection(before)))["route"] == "ask_user"


def test_a_question_already_answered_is_not_asked_again(before, fx):
    fn, _ = node_fn("settlement_auditor", overrides={"expected_settlement": needs(fx, "Q-CONDITION-TYPE")})
    out = run(fn({**before, "answers": {"Q-CONDITION-TYPE": None}}))   # skipped by the user
    assert out["route"] == "audit_rows"


@pytest.mark.parametrize("qid", ["Q-POLICY-PERIOD", "Q-TIE-REJECTION"])
def test_questions_the_claim_cannot_answer_are_not_asked(before, fx, qid):
    fn, _ = node_fn("settlement_auditor", overrides={"expected_settlement": needs(fx, qid)})
    out = run(fn(before))
    assert out["route"] == "audit_rows" and qid in [q["question_id"] for q in out["questions"]]


def test_a_partly_tested_row_is_retested_with_every_method(before, fx):
    real, seen = rows(fx), []

    def reproduce(case, letter, row_id, hypothesis_ids=None):
        seen.append(row_id)
        r = json.loads(json.dumps(real[row_id]))
        if row_id == "R3" and seen.count("R3") == 1:
            r.update(verdict="not_verifiable", exhaustive=False)
        return r
    fn, _ = node_fn("settlement_auditor", overrides={"reproduce_deduction": reproduce})
    out = run(fn(before))
    assert seen.count("R3") == 2 and out["row_audits"]["R3"]["verdict"] == "does_not_match_policy"
    assert "re-tested ['R3']" in out["trace"][0]


def test_a_row_the_engine_cannot_find_is_skipped(before, fx):
    real = rows(fx)

    def reproduce(case, letter, row_id, hypothesis_ids=None):
        if row_id == "R2":
            raise tool_error("reproduce_deduction", "ROW_NOT_FOUND")
        return real[row_id]
    fn, _ = node_fn("settlement_auditor", overrides={"reproduce_deduction": reproduce})
    out = run(fn(before))
    assert "R2" not in out["row_audits"] and out["route"] == "audit_rows"


def test_any_other_row_error_ends_the_run(before, fx):
    def reproduce(case, letter, row_id, hypothesis_ids=None):
        raise tool_error("reproduce_deduction", "POLICY_MISMATCH")
    fn, _ = node_fn("settlement_auditor", overrides={"reproduce_deduction": reproduce})
    out = run(fn(before))
    assert out["outcome"] == "tool_error" and out["route"] == "fix_case_assembly"


def test_rejection_letters_audit_the_rejection_row(before, fx):
    letter = {**before["letter"], "letter_type": "rejection", "rows": [], "copay_amount": None}
    asked = []

    def reproduce(case, letter, row_id, hypothesis_ids=None):
        asked.append(row_id)
        return {**rows(fx)["R3"], "row_id": row_id}
    fn, _ = node_fn("settlement_auditor", overrides={"reproduce_deduction": reproduce})
    run(fn({**before, "letter": letter}))
    assert asked == ["REJECTION"]


# --------------------------------------------------------------------------- the ask_user pause (through the graph)


def loose(dataset_id: str) -> dict:
    """Replay engine results by row ID, whatever the claim (the recording only has the answered claim)."""
    fx = load(dataset_id)
    first = {}
    for c in fx["calls"]:
        name = json.loads(c["key"])[0]
        if name == "reproduce_deduction":
            first.setdefault(("row", json.loads(c["key"])[1][2]), c["result"])
        elif name in ("expected_settlement", "audit_settlement_letter"):
            first.setdefault(name, c["result"])
    copy = lambda v: json.loads(json.dumps(v))                   # noqa: E731
    open_q = (first.get("expected_settlement") or {}).get("questions") or []

    def row(case, letter, row_id, h=None):
        r = copy(first[("row", row_id)])
        if open_q and not case["claim"].get("condition_type"):      # an engine that can't settle it from the letter
            r = {**r, "verdict": "not_verifiable", "questions": copy(open_q)}
        return r
    return {"reproduce_deduction": row,
            "audit_settlement_letter": lambda case, letter, h=None: copy(first["audit_settlement_letter"]),
            "expected_settlement": lambda case: copy(first["expected_settlement"])}


def test_a_skipped_answer_is_recorded_and_the_audit_goes_on():
    c = Case("SET-32", overrides=loose("SET-32"))
    run(c.start())
    final = run(c.gate.answer_questions(c.cfg, {"Q-CONDITION-TYPE": None}))
    assert final["answers"] == {"Q-CONDITION-TYPE": None}
    assert "Q-CONDITION-TYPE unanswered" in "\n".join(final["trace"])
    assert final["outcome"] in ("needs_information", "no_grievance")    # finishes; never asks again


def test_an_invalid_answer_is_rejected_not_applied():
    c = Case("SET-32", overrides=loose("SET-32"))
    run(c.start())
    final = run(c.gate.answer_questions(c.cfg, {"Q-CONDITION-TYPE": "flu"}))
    assert final["answers"] == {"Q-CONDITION-TYPE": None} and final["claim"].get("condition_type") is None
    assert "rejected" in "\n".join(final["trace"])


def test_an_empty_resume_counts_as_no_answers():
    c = Case("SET-32", overrides=loose("SET-32"))
    run(c.start())
    final = run(c.gate.answer_questions(c.cfg, {}))
    assert final["answers"] == {"Q-CONDITION-TYPE": None}
