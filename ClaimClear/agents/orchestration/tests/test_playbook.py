"""The playbook (E3): off by default, lessons only for their step and when their keywords match. No model calls."""
from __future__ import annotations

from claimclear_graph import extraction, playbook


def test_off_by_default_the_prompt_is_unchanged(monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_PLAYBOOK", raising=False)
    assert playbook.lessons("document_reader", "anything") == []
    assert "Lessons from earlier cases" not in extraction._prompt("Platelets 5000")


def test_on_only_matching_lessons_for_the_step(monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_PLAYBOOK", "on")
    ids = {l["id"] for l in playbook.lessons("document_reader", "Platelets SDP 5000")}
    assert {"X1", "X2", "X3", "X5"} <= ids and "X6" not in ids          # X6 needs "co-pay" in the text
    assert all(l["step"] == "document_reader" for l in playbook.lessons("document_reader", "x"))
    assert "H1" not in {l["id"] for l in playbook.lessons("auditor", "x")}  # rejected lessons are never used


def test_on_the_lessons_go_between_the_instructions_and_the_documents(monkeypatch):
    monkeypatch.setenv("CLAIMCLEAR_PLAYBOOK", "on")
    p = extraction._prompt("Co-payment 5% 1875")
    assert p.index("never compute") < p.index("Lessons from earlier cases") < p.index("<documents>")
    assert "co-payment line on the letter is one row" in p and "Co-payment 5% 1875" in p
