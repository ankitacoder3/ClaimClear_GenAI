"""The five insurer letters in the synthetic dataset, against the manifest's expected verdicts.

The letter is loaded with ``load_letter``, which copies only what is printed on
it. The expected verdicts and amounts are read separately from the answer key.
"""

from dataclasses import asdict
from decimal import Decimal

import pytest

from engine import Verdict, audit_letter
from engine.dataset import answer_key, load_case, load_letter

LETTERS = ["SET-01", "SET-02", "SET-03", "SET-04", "SET-05"]


def audit(doc_id, dataset_dir):
    case = load_case(doc_id, dataset_dir)
    return audit_letter(load_letter(doc_id, dataset_dir), case.claim, case.policy, case.rules, case.history)


@pytest.mark.parametrize("doc_id", LETTERS)
def test_row_verdicts_match_the_answer_key(doc_id, dataset_dir):
    key = answer_key(doc_id, dataset_dir)
    a = audit(doc_id, dataset_dir)
    for i, expected in enumerate(key["insurer_deductions"], start=1):
        assert a.row(f"R{i}").verdict.value == expected["expected_verdict"], f"{doc_id} R{i}"
    if key["rejection_expected_verdict"]:
        assert a.row("REJECTION").verdict.value == key["rejection_expected_verdict"]


@pytest.mark.parametrize("doc_id", LETTERS)
def test_rupee_summary_matches_the_answer_key(doc_id, dataset_dir):
    key = answer_key(doc_id, dataset_dir)
    a = audit(doc_id, dataset_dir)
    assert a.policy_payable == Decimal(str(key["expected_payable"]))
    assert a.insurer_paid == Decimal(str(key["insurer_paid"]))
    assert a.disputable_amount == Decimal(str(key["disputable_amount"]))
    assert a.unverified_amount == Decimal(str(key["unverified_amount"]))
    assert a.letter_arithmetic_gap == 0


@pytest.mark.parametrize("doc_id, row_id, method", [
    ("SET-01", "R3", "prop_on_all_lines"),
    ("SET-03", "R1", "cataract_15pct_si"),
    ("SET-05", "REJECTION", "waiting_from_renewal"),
])
def test_insurer_method_identified(doc_id, row_id, method, dataset_dir):
    assert audit(doc_id, dataset_dir).row(row_id).method == method


@pytest.mark.parametrize("doc_id, verdict", [
    ("SET-01", Verdict.METHOD_MATCHES),
    ("SET-02", Verdict.MATCHES_POLICY),
    ("SET-03", Verdict.METHOD_MATCHES),
    ("SET-04", Verdict.METHOD_MATCHES),
])
def test_copay_rows(doc_id, verdict, dataset_dir):
    assert audit(doc_id, dataset_dir).row("COPAY").verdict == verdict


def test_set02_no_false_alarm(dataset_dir):
    a = audit("SET-02", dataset_dir)
    assert all(r.verdict == Verdict.MATCHES_POLICY for r in a.rows)
    assert not a.questions


def test_set04_asks_for_a_breakdown(dataset_dir):
    a = audit("SET-04", dataset_dir)
    assert [q.question_id for q in a.questions] == ["Q-BREAKDOWN-R2"]


def test_set05_notes_the_non_payables_the_rejection_hid(dataset_dir):
    a = audit("SET-05", dataset_dir)
    assert len(a.policy_deductions_not_on_letter) == 1 and "₹1,800" in a.policy_deductions_not_on_letter[0]


@pytest.mark.parametrize("doc_id", LETTERS)
def test_letter_loader_copies_no_answers(doc_id, dataset_dir):
    text = str(asdict(load_letter(doc_id, dataset_dir)))
    for leak in ("expected_verdict", "expected_amount", "expected_payable", "disputable", "insurer_method"):
        assert leak not in text
