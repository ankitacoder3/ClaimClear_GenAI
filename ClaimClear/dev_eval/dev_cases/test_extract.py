"""The extraction stand-in reads every dev case, and what it reads adds up."""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract  # noqa: E402


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def test_every_dev_case_is_extracted():
    out = extract.extract("dev")
    assert len(out) == 42 and not [k for k, v in out.items() if "error" in v]
    assert all("claim" in v and "letter" in v for v in out.values())


def test_gen_data_bills_and_letters_reconcile():
    out = {k: v for k, v in extract.extract("dev").items() if k.startswith("gen-")}
    assert len(out) == 20
    for case_id, v in out.items():
        claim, letter = v["claim"], v["letter"]
        lines = sum(_d(li["amount"]) for li in claim["lines"])
        assert lines - _d(claim["discount"]) == _d(claim["printed_total"]), case_id
        if letter["letter_type"] == "settlement":
            rows = sum(_d(r["amount"]) for r in letter["rows"])
            assert _d(letter["claimed_amount"]) - rows - _d(letter["copay_amount"]) == _d(letter["paid_amount"]), case_id
        else:
            assert letter["rejection_reason"] and _d(letter["paid_amount"]) == 0, case_id


def test_a_wrapped_layout_and_other_bills_are_read():
    v = extract.extract("dev")["gen-dev-3ce156"]
    dated = [li for li in v["claim"]["lines"] if li["date"]]
    assert {li["description"].split(" (")[0] for li in dated} >= {"Multivitamin tonic", "Follow-up blood count"}
    assert v["letter"]["copay_amount"] is not None
