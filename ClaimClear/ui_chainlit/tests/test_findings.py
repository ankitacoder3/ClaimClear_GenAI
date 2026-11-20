"""The findings message built from Member 3's explainer draft (findings.render)."""
from __future__ import annotations

from findings import render

DISCLAIMER = "ClaimClear explains your settlement against your policy wording. It is guidance, not a decision."
NOTE = "Note: your policy also allows a deduction the letter doesn't show: Room rent above the limit: ₹19,000."
STATE = {
    "letter_audit": {"insurer_paid": 63025, "policy_payable": 42395.91, "disputable_amount": 0, "rows": [
        {"row_id": "R1", "particulars": "Gauze | cotton", "insurer_amount": 550, "policy_amount": 550,
         "verdict": "matches_policy"}]},
    "draft": {"sentences": [
        {"text": "The insurer paid ₹63,025. Checked against your policy, the amount payable works out to ₹42,395.91.",
         "fact_ids": ["F-PAYABLE"]},
        {"text": "R1, Gauze and cotton: the insurer deducted ₹550; your policy allows ₹550. Verdict: matches your policy.",
         "row_ids": ["R1"]},
        {"text": "Nothing on this letter looks disputable under your policy."},
        {"text": NOTE}, {"text": NOTE},                                    # the explainer repeats a note
        {"text": DISCLAIMER}]},
    "explanation": "one long paragraph"}


def test_summary_bullets_rows_folded_and_no_repeats():
    message, rows = render(STATE)
    assert message.startswith("### What I found\n**Insurer paid** ₹63,025 · **Your policy allows** ₹42,395.91")
    assert "| R1 | Gauze / cotton | ₹550 | ₹550 |" in message                  # a | in a name can't break the table
    assert "**In short**\n- Nothing on this letter looks disputable under your policy.\n- " + NOTE in message
    assert message.count("Room rent above the limit") == 1
    assert message.endswith(f"_{DISCLAIMER}_")
    assert "The insurer paid ₹63,025. Checked" not in message                 # already in the totals line
    assert rows == [STATE["draft"]["sentences"][1]["text"]]                    # for the folded "Row by row" step
    assert "one long paragraph" not in message


def test_without_a_draft_the_explanation_is_shown_as_written():
    message, rows = render({**STATE, "draft": None})
    assert message.endswith("one long paragraph") and rows == []
