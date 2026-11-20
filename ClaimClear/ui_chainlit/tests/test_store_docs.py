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
