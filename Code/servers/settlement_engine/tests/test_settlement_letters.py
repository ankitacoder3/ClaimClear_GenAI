"""The five settlement letters in the synthetic dataset, against hand-worked answers.

The expected numbers below were worked out by hand (and are checked by the
dataset's own ``verify_dataset.py``). They are NOT produced by this engine, so
the test is not circular.
"""

from decimal import Decimal

import pytest

from engine import DeductionKind, Status, compute_settlement, load_rules
from engine.dataset import answer_key, load_case

# doc_id: (payable under the policy, insurer paid, unverified after co-pay)
HAND = {
    "SET-01": (Decimal("95617.50"), Decimal("87094.64"), Decimal("0")),
    "SET-02": (Decimal("93660.50"), Decimal("93660.50"), Decimal("0")),
    "SET-03": (Decimal("36575.00"), Decimal("28500.00"), Decimal("0")),
    "SET-04": (Decimal("82745.00"), Decimal("78280.00"), Decimal("4465.00")),
    "SET-05": (Decimal("81985.00"), Decimal("0"), Decimal("0")),
}


def settle(doc_id, dataset_dir):
    case = load_case(doc_id, dataset_dir)
    return compute_settlement(case.claim, case.policy, case.rules, case.history)


@pytest.mark.parametrize("doc_id", sorted(HAND))
def test_payable_matches_hand_worked_figure(doc_id, dataset_dir):
    r = settle(doc_id, dataset_dir)
    assert r.status == Status.COMPUTED
    assert r.payable_amount == HAND[doc_id][0]


@pytest.mark.parametrize("doc_id", sorted(HAND))
def test_payable_matches_manifest(doc_id, dataset_dir):
    assert settle(doc_id, dataset_dir).payable_amount == Decimal(str(answer_key(doc_id, dataset_dir)["expected_payable"]))


@pytest.mark.parametrize("doc_id", sorted(HAND))
def test_gap_to_insurer_equals_disputable_plus_unverified(doc_id, dataset_dir):
    key = answer_key(doc_id, dataset_dir)
    gap = settle(doc_id, dataset_dir).payable_amount - Decimal(str(key["insurer_paid"]))
    assert gap == Decimal(str(key["disputable_amount"])) + Decimal(str(key["unverified_amount"]))


@pytest.mark.parametrize("doc_id", sorted(HAND))
def test_claimed_amount_matches_the_letter(doc_id, dataset_dir):
    assert settle(doc_id, dataset_dir).claimed_amount == Decimal(str(answer_key(doc_id, dataset_dir)["claimed_amount"]))


def test_set01_deductions(dataset_dir):
    r = settle("SET-01", dataset_dir)
    assert r.deduction(DeductionKind.ROOM_RENT_EXCESS).amount == Decimal("6000.00")
    assert r.deduction(DeductionKind.ROOM_GST_EXCESS).amount == Decimal("300.00")
    assert r.deduction(DeductionKind.PROPORTIONATE).amount == Decimal("21400.00")   # insurer: 30,371.43
    assert r.copay_amount == Decimal("5032.50")


def test_set01_expected_amounts_from_manifest(dataset_dir):
    """The letter's three rows, in order, against the engine's deductions of the same kind."""
    r = settle("SET-01", dataset_dir)
    kinds = [DeductionKind.ROOM_RENT_EXCESS, DeductionKind.ROOM_GST_EXCESS, DeductionKind.PROPORTIONATE]
    for row, kind in zip(answer_key("SET-01", dataset_dir)["insurer_deductions"], kinds):
        assert r.deduction(kind).amount == Decimal(str(row["expected_amount"]))


def test_set02_only_listed_consumables(dataset_dir):
    r = settle("SET-02", dataset_dir)
    assert [d.kind for d in r.deductions] == [DeductionKind.NON_PAYABLE]
    assert r.deductions[0].amount == Decimal("3360.00")


def test_set03_no_cataract_deduction(dataset_dir):
    r = settle("SET-03", dataset_dir)
    assert r.fact("F-CATARACT-LIMIT").amount == Decimal("40000.00")   # not 15% of SI = 30,000
    assert r.deduction(DeductionKind.CATARACT_LIMIT) is None          # expected_amount 0


def test_set04_has_no_basis_for_4700(dataset_dir):
    r = settle("SET-04", dataset_dir)
    assert [d.amount for d in r.deductions] == [Decimal("2900.00")]
    assert r.claimed_amount == Decimal("90000.00")                     # net of the ₹1,100 discount


def test_set05_waiting_period_served(dataset_dir):
    r = settle("SET-05", dataset_dir)
    assert r.deduction(DeductionKind.WAITING_PERIOD) is None
    assert r.fact("F-WAITING").inputs["served"] is True


def test_dataset_rules_file_matches_defaults(dataset_dir, rules):
    assert load_rules(dataset_dir / "policy_rules.json") == rules
