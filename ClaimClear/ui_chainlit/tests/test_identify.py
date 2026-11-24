"""Identifying uploads (identify.py): one structured LLM call per document, recorded in the (fake) case store."""
from __future__ import annotations

from conftest import BILL, LETTER, FakeToolkit, ScriptedModel, run
from claimclear_graph.testing import tool_error
from identify import identify_documents

SCHEDULE = ["POLICY SCHEDULE\nPolicy No. AS/2025/658678/79\nInsured: Prakash N. Reddy"]


def toolkit():
    return FakeToolkit({"DOC-1": BILL, "DOC-2": LETTER, "DOC-3": SCHEDULE, "DOC-W": ["wording"] * 71},
                       names={"DOC-1": "scan001.pdf", "DOC-2": "letter.pdf", "DOC-3": "", "DOC-W": "terms.pdf"})


def test_each_document_is_identified_and_recorded(fake_store_writes):
    tk = toolkit()
    llm = ScriptedModel(identities=[
        {"type": "bill", "summary": "City Eye Hospital final bill"},
        {"type": "settlement_letter", "summary": "Claim settlement advice, paid INR 7,125.00"},
        {"type": "policy_schedule", "summary": "Policy schedule", "policy_no": "AS/2025/658678/79"},
        {"type": "policy_wording", "summary": "Arogya Sanjeevani policy wording"}])
    found = run(identify_documents(llm, tk, "C"))
    assert [(d["name"], d["type"]) for d in found] == [("scan001.pdf", "bill"), ("letter.pdf", "settlement_letter"),
                                                        ("DOC-3", "policy_schedule"), ("terms.pdf", "policy_wording")]
    assert ("describe", "C", "DOC-2", "settlement_letter", "Claim settlement advice, paid INR 7,125.00") in fake_store_writes
    assert ("policy", "C", "AS/2025/658678/79", "") in fake_store_writes                  # the schedule's number
    assert ("schedule", "C", {"policy_no": "AS/2025/658678/79"}) in fake_store_writes      # its terms, as read
    assert ("wording", "C", "upload:DOC-W") in fake_store_writes and found[3]["note"].startswith("indexed for search")
    assert tk.meta["DOC-1"] == {"role": "bill", "name": "scan001.pdf", "summary": "City Eye Hospital final bill"}
    assert "File name (a hint only" in llm.prompts[0] and "scan001.pdf" in llm.prompts[0]
    assert "Cataract surgery" in llm.prompts[0] and "Page 1 of 2" in llm.prompts[0]
    assert all(c[3] == [1] for c in tk.calls if c[0] == "get_document_text" and c[2] != "DOC-W")   # page 1 only


def test_only_documents_without_a_summary(fake_store_writes):
    tk = toolkit()
    for d in ("DOC-1", "DOC-2", "DOC-3"):
        tk.meta[d]["summary"] = "already known"
    found = run(identify_documents(ScriptedModel(identities=[{"type": "policy_wording", "summary": "w"}]), tk, "C"))
    assert [d["document_id"] for d in found] == ["DOC-W"]


def test_a_document_that_cant_be_read_is_reported(fake_store_writes):
    class Unreadable(FakeToolkit):
        async def get_document_text(self, case_id, document_id, pages=None):
            raise tool_error("get_document_text", "DOCUMENT_ENCRYPTED", "password protected")
    found = run(identify_documents(ScriptedModel(), Unreadable({"DOC-1": BILL}, names={"DOC-1": "bill.pdf"}), "C"))
    assert found == [{"document_id": "DOC-1", "name": "bill.pdf",
                      "error": "get_document_text: DOCUMENT_ENCRYPTED: password protected"}]
    assert fake_store_writes == []
