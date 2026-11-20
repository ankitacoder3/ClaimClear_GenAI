"""Retrieval metrics at k for the retrieval report.

Queries are JSON lines::

    {"id": "q01", "query": "why did they cut my medicine bill", "relevant": ["5.2", "5.1"], "note": "..."}

``relevant`` lists the clause IDs a correct answer must cite. Metrics per configuration, each the mean over
the queries:

* **recall@k**: share of the query's relevant clauses found in the top k (the plan's Recall@5);
* **precision@k**: share of the top k that is relevant, ``relevant found / k``. With one or two relevant
  clauses per query its ceiling is low (0.2-0.4 at k = 5), so read it next to recall;
* **map@k**: average precision at k, ``sum(precision@i for each rank i holding a relevant clause) /
  min(len(relevant), k)``: rewards ranking *every* relevant clause high, not only the first;
* **hit@k**: share of queries with at least one relevant clause in the top k;
* **mrr**: mean reciprocal rank of the first relevant clause.

``compare`` runs the plan's grid: BM25, vectors, hybrid and hybrid + reranker, each
without and with query rewriting.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from .kb import PolicyKB, _normalise_id
from .rewrite import NoRewriter, Rewriter


@dataclass(frozen=True)
class Query:
    id: str
    query: str
    relevant: tuple[str, ...]
    note: str = ""


@dataclass
class Report:
    config: str
    k: int
    queries: int
    recall: float
    hit: float
    mrr: float
    misses: list[str]
    precision: float = 0.0
    map: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def load_queries(path: str | Path) -> list[Query]:
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        if not d.get("relevant"):
            raise ValueError(f"line {n}: 'relevant' must list at least one clause ID")
        out.append(Query(str(d.get("id", n)), d["query"], tuple(d["relevant"]), d.get("note", "")))
    return out


def check_labels(kb: PolicyKB, queries: Iterable[Query]) -> list[str]:
    """Clause IDs in the labels that don't exist in the index (a label error, or the wrong wording)."""
    return sorted({r for q in queries for r in q.relevant if kb.get_clause(r) is None})


def evaluate(kb: PolicyKB, queries: list[Query], k: int = 5, mode: str = "hybrid", rerank: bool = False,
             config: Optional[str] = None) -> Report:
    recall = hit = mrr = precision = ap_sum = 0.0
    misses = []
    for q in queries:
        relevant = {_normalise_id(r) for r in q.relevant}
        found = [_normalise_id(h.clause_id) for h in kb.search(q.query, k=k, mode=mode, rerank=rerank)][:k]
        got = relevant & set(found)
        recall += len(got) / len(relevant)
        precision += len(got) / k
        hit += 1.0 if got else 0.0
        first = next((i for i, c in enumerate(found, start=1) if c in relevant), None)
        mrr += 1.0 / first if first else 0.0
        ap_sum += average_precision(found, relevant, k)
        if not got:
            misses.append(q.id)
    n = max(len(queries), 1)
    return Report(config or mode, k, len(queries), round(recall / n, 4), round(hit / n, 4), round(mrr / n, 4), misses,
                  precision=round(precision / n, 4), map=round(ap_sum / n, 4))


def average_precision(found: list[str], relevant: set[str], k: int) -> float:
    """AP@k: the mean of precision@i over the ranks i (<= k) that hold a relevant clause, divided by
    ``min(len(relevant), k)`` so a query with more relevant clauses than k can still score 1.0."""
    hits, total = 0, 0.0
    for i, clause in enumerate(found[:k], start=1):
        if clause in relevant:
            hits += 1
            total += hits / i
    return total / min(len(relevant), k) if relevant else 0.0


def compare(kb: PolicyKB, queries: list[Query], k: int = 5, rewriter: Optional[Rewriter] = None,
            include_rerank: bool = True) -> list[Report]:
    """The plan's grid, without and with rewriting."""
    plain = kb.with_rewriter(NoRewriter())
    rewritten = kb.with_rewriter(rewriter or kb.rewriter)
    rows = []
    for label, base in (("no rewrite", plain), (f"rewrite:{rewritten.rewriter.name}", rewritten)):
        for mode in ("bm25", "vector", "hybrid"):
            rows.append(evaluate(base, queries, k, mode, False, f"{mode}, {label}"))
        if include_rerank and base.reranker.name != "none":
            rows.append(evaluate(base, queries, k, "hybrid", True, f"hybrid+rerank, {label}"))
    return rows


def format_table(rows: list[Report]) -> str:
    k = rows[0].k if rows else 5
    lines = [f"| Configuration | Recall@{k} | Precision@{k} | MAP@{k} | Hit@{k} | MRR | Missed |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.config} | {r.recall:.3f} | {r.precision:.3f} | {r.map:.3f} | {r.hit:.3f} | {r.mrr:.3f} | "
                     f"{', '.join(r.misses) or '-'} |")
    return "\n".join(lines)
