import json

import pytest

from policy_kb import GlossaryRewriter, LLMRewriter, NoRewriter, PolicyKB
from policy_kb.bm25 import BM25
from policy_kb.embedders import HashingEmbedder, cosine, make_embedder
from policy_kb.kb import _normalise_id


# --- building blocks ------------------------------------------------------------------------


def test_bm25_prefers_documents_with_rare_query_terms():
    bm = BM25(["room rent limit per day", "co-payment of five percent", "room category and nursing"])
    s = bm.scores("co-payment percent")
    assert s.index(max(s)) == 1 and s[0] == 0


def test_hashing_embedder_is_deterministic_and_normalised():
    a, b = HashingEmbedder(256), HashingEmbedder(256)
    v = a.embed_query("proportionate deduction")
    assert v == b.embed_query("proportionate deduction")
    assert abs(cosine(v, v) - 1) < 1e-9
    assert cosine(v, a.embed_query("proportionate deductions")) > cosine(v, a.embed_query("ombudsman"))


def test_make_embedder_names():
    assert make_embedder("hashing").name == "hashing-1024" and make_embedder("hashing-64").dims == 64
    with pytest.raises(ValueError):
        make_embedder("word2vec")


@pytest.mark.parametrize("raw, norm", [("5.2", "5.2"), ("Clause 5.2", "5.2"), ("5.2.", "5.2"),
                                       ("annexure i", "Annexure I"), ("Section 7.1", "7.1")])
def test_clause_id_normalisation(raw, norm):
    assert _normalise_id(raw) == norm


def test_glossary_rewriter_adds_policy_terms_and_keeps_the_words():
    q = GlossaryRewriter()("why did they cut my medicine bill")
    assert q.startswith("why did they cut my medicine bill") and "pharmacy" in q and "deduction" in q
    assert GlossaryRewriter()("ombudsman") == "ombudsman"            # nothing to add


def test_llm_rewriter_appends_the_model_output():
    rw = LLMRewriter(lambda prompt: "proportionate deduction pharmacy" if "medicine" in prompt else "")
    assert rw("medicine cut") == "medicine cut proportionate deduction pharmacy"
    assert rw("hello") == "hello"


# --- search -------------------------------------------------------------------------------------


@pytest.mark.parametrize("query, expected", [
    ("why did they cut my medicine bill", "5.2"),
    ("how do I complain about the settlement", "10.1"),
    ("does the waiting period restart on renewal", "7.5"),
    ("cataract limit per eye", "4.3"),
    ("gloves and masks were deducted", "8"),
])
def test_search_finds_the_clause(kb, query, expected):
    assert expected in [h.clause_id for h in kb.search(query, k=3)]


def test_exact_policy_terms_work_without_rewriting(kb):
    hits = kb.search("proportionate deduction does not apply to pharmacy consumables implants", k=1, rewrite=False)
    assert hits[0].clause_id == "5.2"


def test_modes_and_ranks(kb):
    for mode in ("bm25", "vector", "hybrid"):
        hits = kb.search("co-payment", k=3, mode=mode)
        assert hits and set(hits[0].ranks) == ({"bm25", "vector"} if mode == "hybrid" else {mode})
    with pytest.raises(ValueError):
        kb.search("x", mode="magic")


def test_hits_carry_provenance(kb):
    h = kb.search("room rent limit", k=1)[0]
    assert h.wording == "SYNHLIP00000V000000" and h.synthetic is True and h.text


def test_headings_without_text_are_not_returned(kb):
    ids = {h.clause_id for q in ("coverage", "definitions", "claim procedure") for h in kb.search(q, k=5)}
    assert not ids & {"3", "4", "9"}


def test_empty_query(kb):
    assert kb.search("   ") == []


def test_get_clause(kb):
    assert kb.get_clause("Clause 5.2").title == "Items not reduced"
    assert kb.get_clause("annexure i").clause_id == "Annexure I"
    assert kb.get_clause("99.9") is None


def test_reranker_reorders_the_fused_candidates(ingested):
    class Prefer:
        name = "fake"
        def rerank(self, query, texts):
            return [1.0 if "Ombudsman" in t else 0.0 for t in texts]
    kb = PolicyKB.build(ingested, reranker=Prefer())
    hits = kb.search("grievance complaint", k=3)
    assert hits[0].clause_id == "10.2" and hits[0].ranks["rerank"] == 1
    assert kb.search("grievance complaint", k=3, rerank=False)[0].ranks.get("rerank") is None


def test_with_rewriter_shares_the_index(kb):
    plain = kb.with_rewriter(None)
    assert plain.rewriter.name == "none" and plain._vectors is kb._vectors


# --- save and load ------------------------------------------------------------------------------


def test_save_and_load_round_trip(kb, tmp_path):
    path = kb.save(tmp_path / "idx.json")
    again = PolicyKB.load(path)
    assert [c.clause_id for c in again.clauses] == [c.clause_id for c in kb.clauses]
    assert again.info == kb.info
    q = "why did they cut my medicine bill"
    assert [h.clause_id for h in again.search(q)] == [h.clause_id for h in kb.search(q)]


def test_load_refuses_a_different_embedder(kb, tmp_path):
    path = kb.save(tmp_path / "idx.json")
    with pytest.raises(ValueError):
        PolicyKB.load(path, embedder=HashingEmbedder(64))


def test_load_refuses_an_unknown_format(kb, tmp_path):
    path = kb.save(tmp_path / "idx.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["format"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        PolicyKB.load(path)
