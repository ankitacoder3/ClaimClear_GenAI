"""Indexing an uploaded policy wording (store_docs.index_wording) with a fake toolkit; no servers."""
from __future__ import annotations

import store_docs
from conftest import FakeToolkit, run
from claimclear_graph.testing import tool_error


def test_a_wording_is_indexed_whole_and_set_on_the_case(fake_store_writes):
    tk = FakeToolkit({"DOC-W": [f"page {i}" for i in range(1, 72)]})
    done = run(store_docs.index_wording(tk, "C", "DOC-W"))
    reads = [c[3] for c in tk.calls if c[0] == "get_document_text"]
    assert reads == [[1], list(range(1, 51)), list(range(51, 72))]          # G9: 50 pages at a time
    (register,) = [c for c in tk.calls if c[0] == "register_uploaded_wording"]
    assert register[2] == "DOC-W" and register[3] == list(range(1, 72))
    assert fake_store_writes == [("wording", "C", "upload:DOC-W")]
    assert done == {"page_count": 71, "pages_indexed": 71, "wording_uin": "upload:DOC-W", "structure": "clauses",
                    "clause_count": 120, "in_scope": True, "error": None}


def test_a_failed_index_is_reported_and_not_set(fake_store_writes):
    class Failing(FakeToolkit):
        async def register_uploaded_wording(self, *a):
            raise tool_error("register_uploaded_wording", "BAD_INPUT", "no text")
    done = run(store_docs.index_wording(Failing({"DOC-W": ["x"] * 20}), "C", "DOC-W"))
    assert done == {"error": "register_uploaded_wording: BAD_INPUT: no text"}
    assert fake_store_writes == []


def test_the_dataset_case_is_found_from_the_files_as_uploaded():
    from pathlib import Path
    folder = Path(store_docs.REPO) / "development" / "dev_data" / "dataset" / "dev" / "cases" / "gen-dev-821b7c"
    ids = [store_docs.file_document_id(p) for p in sorted(folder.glob("*.pdf"))]
    if not (Path(store_docs.REPO) / "var" / "dataset_map.json").exists():
        import pytest
        pytest.skip("no dataset map on this machine (built by start.py)")
    assert store_docs.dataset_reference_key(ids) == "gen-dev-821b7c"


def test_a_shared_policy_number_is_resolved_by_the_schedule():
    facts = {"patient_name": "Imran S. Khan", "sum_insured": "Rs. 2,50,000/-"}
    assert store_docs.reference_key_by_policy("AS/2026/320305/49", {**facts, "first_inception": "10/01/2022"}) == "gen-dev-81d177"
    assert store_docs.reference_key_by_policy("AS/2026/320305/49", {**facts, "first_inception": "10-Jan-2024"}) == "gen-dev-e8b46c"
    assert store_docs.reference_key_by_policy("AS/2026/131805/71", {}) == ""       # one shared record: no key needed


def test_schedule_terms_and_the_note_say_where_the_policy_comes_from():
    facts = {"policy_no": "NEW-POLICY-1", "patient_name": "Asha Menon", "sum_insured": "Rs. 3,00,000/-",
             "period_start": "01/04/2026", "period_end": "31-Mar-2027", "first_inception": "01/04/2024"}
    t = store_docs.schedule_terms(facts)
    assert t == {"holder": "Asha Menon", "policy_no": "NEW-POLICY-1", "sum_insured": 300000.0,
                 "period_start": "2026-04-01", "period_end": "2027-03-31", "first_inception": "2024-04-01"}
    note = store_docs.policy_source_note("NEW-POLICY-1", facts)
    assert note.startswith("**Policy terms:** from your uploaded policy schedule") and "isn't in ClaimClear" in note
    known = store_docs.policy_source_note("AS-2026-102011", {**facts, "period_start": None})
    assert "standard records for policy AS-2026-102011" in known and "isn't in" not in known
    assert "standard records" in store_docs.policy_source_note("AS-2026-102011", None)
    assert "clearer copy" in store_docs.policy_source_note("NEW-POLICY-1", {"sum_insured": "Rs. 1"})
