"""The documents-must-agree check and the choice of the current settlement letter (plain code, made-up fact sheets)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from security import consistency_check as cc  # noqa: E402


def doc(i, kind, name=None, **facts):
    return {"document_id": i, "name": name or f"{i}.pdf", "type": kind, "facts": facts}


BILL = doc("b", "bill", "bill.pdf", patient_name="Prakash N. Reddy", admission_date="05/10/2026",
           discharge_date="06/10/2026", hospital="Lotus Eye Care")
SCHEDULE = doc("s", "policy_schedule", "schedule.pdf", patient_name="Mr. Prakash Reddy", policy_no="AS/2025/658678/79",
               sum_insured="Rs. 1,50,000/-")
LETTER = doc("l", "settlement_letter", "letter.pdf", patient_name="Prakash N. Reddy", policy_no="AS/2025/658678/79",
             claim_no="CLM/2026/2738155", document_date="11/10/2026", admission_date="05/10/2026",
             discharge_date="06/10/2026", sum_insured="Rs. 1,50,000/-")
EARLIER = doc("e", "settlement_letter", "earlier_settlement_1.pdf", patient_name="Prakash N. Reddy",
              policy_no="AS/2025/658678/79", claim_no="CLM/2026/2738100", document_date="26/02/2026",
              admission_date="12/02/2026")


def test_reading_the_facts():
    assert cc.same_person("Prakash N. Reddy", "Mr. Prakash Reddy") is True
    assert cc.same_person("Rekha D. Rao", "REKHA DEVI RAO") is True                    # initial ~ full name
    assert cc.same_person("Parashkar Singh", "Parashar Singh") is False
    assert cc.same_person(None, "Anyone") is None
    assert cc.number("Rs. 2,50,000/-") == 250000 and cc.number("INR 1,50,000.00") == 150000
    assert cc.day("12-Feb-2026") == cc.day("12/02/2026") == cc.day("12 February 2026") == date(2026, 2, 12)
    assert cc.policy_key("AS/2025/658678/79") == cc.policy_key("as 2025 658678 79")


def test_consistent_documents_raise_nothing():
    assert cc.check([BILL, SCHEDULE, LETTER]) == []


def test_the_current_letter_is_the_one_for_this_stay():
    pick = cc.pick_current_letter([BILL, SCHEDULE, EARLIER, LETTER])
    assert pick["current"] == "l" and pick["earlier"] == ["e"] and not pick["ambiguous"]
    assert "patient and admission date" in pick["reason"]
    assert cc.earlier_summary(EARLIER).startswith("Earlier settlement letter (a previous claim): claim CLM/2026/2738100")


def test_one_letter_is_left_alone_and_two_unclear_letters_are_ambiguous():
    assert cc.pick_current_letter([BILL, LETTER]) == {"current": "l", "earlier": [], "reason": "", "ambiguous": False}
    a, b = doc("x", "settlement_letter"), doc("y", "settlement_letter")
    assert cc.pick_current_letter([a, b])["ambiguous"]


def test_a_letter_for_another_patient_and_policy():                                   # RT-A12
    other = doc("l", "settlement_letter", "letter.pdf", patient_name="Asha R. Menon", policy_no="AS/2026/112233/10",
                admission_date="05/10/2026")
    reasons = [f.reason for f in cc.check([BILL, SCHEDULE, other])]
    assert "the patient's name differs" in reasons and "the policy number differs" in reasons


def test_sum_insured_name_and_dates():                                                # RT-D01, D02, D04
    letter = {**LETTER, "facts": {**LETTER["facts"], "sum_insured": "Rs. 2,00,000/-", "admission_date": "19/09/2026"}}
    bill = {**BILL, "facts": {**BILL["facts"], "patient_name": "Prakash Rao"}}
    found = {f.reason for f in cc.check([bill, SCHEDULE, letter])}
    assert any(r.startswith("the sum insured differs") for r in found)
    assert "the admission date differs" in found and "the patient's name differs" in found
    assert all(f.category == "consistency" for f in cc.check([bill, SCHEDULE, letter]))


def test_an_earlier_claim_for_the_same_stay_is_flagged():                             # RT-D05
    same_stay = {**EARLIER, "facts": {**EARLIER["facts"], "admission_date": "05/10/2026"}}
    found = cc.check([BILL, SCHEDULE, LETTER, same_stay], current_letter="l")
    assert any("same hospital stay" in f.reason for f in found)
    assert cc.check([BILL, SCHEDULE, LETTER, EARLIER], current_letter="l") == []      # a real earlier claim is fine


def test_the_message_names_each_disagreement():
    other = {**LETTER, "facts": {**LETTER["facts"], "sum_insured": "Rs. 2,00,000/-"}}
    msg = cc.message(cc.check([BILL, SCHEDULE, other]))
    assert msg.startswith("**⚠️ Your documents don't agree**") and "sum insured" in msg
