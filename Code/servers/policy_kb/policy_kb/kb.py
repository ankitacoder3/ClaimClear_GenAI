"""``PolicyKB``: the policy knowledge base. Build it once from a wording, then search it.

    kb = PolicyKB.from_file("wording.pdf", WordingInfo(...))       # ingest + index
    kb.save("var/policy_kb/index.json")
    kb = PolicyKB.load("var/policy_kb/index.json")
    hits = kb.search("they cut my medicine bill", k=5)              # list[SearchHit]
    clause = kb.get_clause("5.2")

Search pipeline (the plan's minimum bar):

    query ──rewrite──► BM25 top-N ─┐
                       vector top-N ┴─► reciprocal rank fusion ─► rerank top-N ─► top-k

* **BM25** catches exact policy terms and clause numbers.
* **Vectors** catch paraphrase (with a real embedding model; the hashing fallback
  only catches spelling variants and shared phrases).
* **Reciprocal rank fusion** (k = 60) combines the two rankings without tuning weights.
* **Reranking** (optional cross-encoder) re-scores the fused top-N.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .bm25 import BM25
from .embedders import Embedder, make_embedder
from .ingest import IngestResult, ingest_file
from .models import Clause, SearchHit, WordingInfo
from .rerankers import Reranker, make_reranker
from .vectorstore import VectorStore, vector_store_for
from .rewrite import GlossaryRewriter, NoRewriter, Rewriter

INDEX_FORMAT = 1
RRF_K = 60
MODES = ("hybrid", "bm25", "vector")


def _normalise_id(clause_id: str) -> str:
    s = re.sub(r"^(clause|section|para(graph)?)\s+", "", clause_id.strip(), flags=re.I)
    s = re.sub(r"\s+", " ", s).rstrip(".")
    m = re.match(r"^(annexure|appendix|schedule)\s*[-–]?\s*([ivxlc]+|\d+|[a-z])(?:\s+list\s+([ivx]+))?$", s, re.I)
    if m:
        base = f"{m.group(1).title()} {m.group(2).upper()}"
        return f"{base} List {m.group(3).upper()}" if m.group(3) else base
    return s.upper() if re.match(r"^[a-z](\.\d+)+$", s) else s


def _ranked(scores: list[float], top: int, positive_only: bool) -> list[int]:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    if positive_only:
        order = [i for i in order if scores[i] > 0]
    return order[:top]


class PolicyKB:
    def __init__(self, info: WordingInfo, clauses: list[Clause], embedder: Embedder,
                 reranker: Optional[Reranker] = None, rewriter: Optional[Rewriter] = None,
                 vectors: Optional[list[list[float]]] = None, vector_store: Optional[VectorStore] = None):
        self.info = info
        self.clauses = list(clauses)
        self.embedder = embedder
        self.reranker = reranker or make_reranker("none")
        self.rewriter = rewriter or GlossaryRewriter()
        self._by_id = {_normalise_id(c.clause_id): c for c in self.clauses}
        self._docs = [c for c in self.clauses if c.text]          # headings without text aren't indexed
        texts = [c.index_text() for c in self._docs]
        self._bm25 = BM25(texts)
        self._vectors = vectors if vectors is not None else embedder.embed_documents(texts)
        if len(self._vectors) != len(self._docs):
            raise ValueError("index vectors don't match the clauses; rebuild the index")
        # where the vector half of hybrid search is ranked: in memory, or pgvector (CLAIMCLEAR_POLICY_KB_VECTORS)
        self._vector_store = vector_store or vector_store_for(
            info.key, embedder.name, self._vectors, [c.clause_id for c in self._docs])

    # ------------------------------------------------------------------ building and storing

    @classmethod
    def build(cls, result: IngestResult, embedder: str | Embedder = "hashing", reranker: str | Reranker = "none",
              rewriter: Optional[Rewriter] = None) -> "PolicyKB":
        emb = make_embedder(embedder) if isinstance(embedder, str) else embedder
        rr = make_reranker(reranker) if isinstance(reranker, str) else reranker
        return cls(result.info, result.clauses, emb, rr, rewriter)

    @classmethod
    def from_file(cls, path: str | Path, info: WordingInfo, embedder: str | Embedder = "hashing",
                  reranker: str | Reranker = "none", rewriter: Optional[Rewriter] = None) -> "PolicyKB":
        return cls.build(ingest_file(path, info), embedder, reranker, rewriter)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "format": INDEX_FORMAT,
            "info": self.info.to_dict(),
            "embedder": self.embedder.name,
            "clauses": [c.to_dict() for c in self.clauses],
            "vectors": [[round(x, 6) for x in v] for v in self._vectors],
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path, reranker: str | Reranker = "none", rewriter: Optional[Rewriter] = None,
             embedder: Optional[Embedder] = None) -> "PolicyKB":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != INDEX_FORMAT:
            raise ValueError(f"index format {data.get('format')} is not supported; rebuild the index")
        emb = embedder or make_embedder(data["embedder"])
        if emb.name != data["embedder"]:
            raise ValueError(f"index was built with {data['embedder']}, not {emb.name}")
        clauses = [Clause(**{**c, "codes": tuple(c.get("codes", ()))}) for c in data["clauses"]]
        rr = make_reranker(reranker) if isinstance(reranker, str) else reranker
        return cls(WordingInfo(**data["info"]), clauses, emb, rr, rewriter, data["vectors"])

    # ------------------------------------------------------------------ lookup and search

    def get_clause(self, clause_id: str) -> Optional[Clause]:
        """A clause by its printed number ("5.2", "Clause 5.2", "annexure i"), or ``None``."""
        return self._by_id.get(_normalise_id(clause_id))

    def search(self, query: str, k: int = 5, mode: str = "hybrid", rewrite: bool = True, rerank: bool = True,
               candidates: int = 20) -> list[SearchHit]:
        """The ``k`` clauses most relevant to ``query``."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not query.strip() or not self._docs:
            return []
        q = self.rewriter(query) if rewrite else query
        ranks: dict[str, dict[int, int]] = {}
        if mode in ("hybrid", "bm25"):
            ranks["bm25"] = {d: r for r, d in enumerate(_ranked(self._bm25.scores(q), candidates, True), start=1)}
        if mode in ("hybrid", "vector"):
            qv = self.embedder.embed_query(q)
            ranks["vector"] = {d: r for r, d in enumerate(self._vector_store.ranked(qv, candidates), start=1)}
        fused: dict[int, float] = {}
        for per in ranks.values():
            for d, r in per.items():
                fused[d] = fused.get(d, 0.0) + 1.0 / (RRF_K + r)
        order = sorted(fused, key=lambda d: fused[d], reverse=True)[:candidates]
        scores = {d: fused[d] for d in order}
        rerank_rank: dict[int, int] = {}
        if rerank and order:
            rs = self.reranker.rerank(query, [self._docs[d].index_text() for d in order])
            if rs is not None:
                scores = dict(zip(order, rs))
                order = sorted(order, key=lambda d: scores[d], reverse=True)
                rerank_rank = {d: r for r, d in enumerate(order, start=1)}
        hits = []
        for d in order[:k]:
            c = self._docs[d]
            hit_ranks = {name: per.get(d) for name, per in ranks.items()}
            if rerank_rank:
                hit_ranks["rerank"] = rerank_rank[d]
            hits.append(SearchHit(c.clause_id, c.title, c.section, c.text, round(float(scores[d]), 6),
                                  c.page_start, c.page_end, self.info.key, self.info.synthetic, hit_ranks))
        return hits

    # ------------------------------------------------------------------ settlement-engine rule map

    def rule_map(self) -> dict:
        """The reviewed map from settlement-engine ``rule_ref`` to clause IDs for this wording
        (``policy_kb/rule_maps/<UIN>.json``), or ``{}`` if there is none."""
        path = Path(__file__).resolve().parent / "rule_maps" / f"{self.info.uin}.json"
        return json.loads(path.read_text(encoding="utf-8")) if self.info.uin and path.exists() else {}

    def clauses_for_rule(self, rule_ref: str) -> list[Clause]:
        """The clauses behind an engine rule, e.g. ``"copay"`` -> [E.28.3, B.10]; the first is the one to cite."""
        ids = (self.rule_map().get("rules", {}).get(rule_ref) or {}).get("clauses", [])
        return [c for c in (self.get_clause(i) for i in ids) if c is not None]

    def check_rule_map(self) -> list[str]:
        """Clause IDs in the rule map that this index doesn't have (should be empty)."""
        missing = []
        for rule, entry in self.rule_map().get("rules", {}).items():
            missing += [f"{rule}: {cid}" for cid in entry.get("clauses", []) if self.get_clause(cid) is None]
        return missing

    def with_rewriter(self, rewriter: Optional[Rewriter]) -> "PolicyKB":
        """The same index with another rewriter (``None`` for no rewriting). Shares the vectors."""
        return PolicyKB(self.info, self.clauses, self.embedder, self.reranker, rewriter or NoRewriter(), self._vectors,
                        self._vector_store)
