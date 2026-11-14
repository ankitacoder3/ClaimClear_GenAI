"""The vector half of hybrid search: in memory (default) and in PostgreSQL + pgvector.

The pgvector tests run against deploy/storage.compose.yml when CLAIMCLEAR_TEST_POSTGRES is set
(e.g. postgresql://claimclear:claimclear@127.0.0.1:5432/claimclear) and are skipped otherwise.
"""

import json
import os
import uuid

import pytest

from conftest import SAMPLE_QUERIES
from policy_kb import PolicyKB
from policy_kb.vectorstore import MemoryVectors, PgVectors, _connect, vector_store_for

PG = os.environ.get("CLAIMCLEAR_TEST_POSTGRES")
needs_pg = pytest.mark.skipif(not PG, reason="set CLAIMCLEAR_TEST_POSTGRES (see deploy/storage.compose.yml)")
QUERIES = [json.loads(line)["query"] for line in SAMPLE_QUERIES.read_text(encoding="utf-8").splitlines()
           if line.strip() and not line.startswith("#")]


def test_default_is_in_memory(kb, monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_POLICY_KB_VECTORS", raising=False)
    assert isinstance(vector_store_for("W", "hashing", [[1.0, 0.0]], ["1"]), MemoryVectors)
    assert isinstance(kb._vector_store, MemoryVectors)


def test_memory_ranking_is_the_dot_product_order(kb):
    qv = kb.embedder.embed_query("room rent limit")
    scores = [sum(a * b for a, b in zip(qv, v)) for v in kb._vectors]
    assert kb._vector_store.ranked(qv, 5) == sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:5]


def test_a_rewritten_copy_shares_the_vector_store(kb):
    from policy_kb import NoRewriter
    assert kb.with_rewriter(NoRewriter())._vector_store is kb._vector_store


@pytest.fixture
def pg_dsn():
    prefix = "pk" + uuid.uuid4().hex[:8] + "_"
    yield f"{PG}{'&' if '?' in PG else '?'}table_prefix={prefix}"
    con = _connect(PG)
    cur = con.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {prefix}vectors")
    cur.execute(f"DROP TABLE IF EXISTS {prefix}vector_sets")
    con.commit()
    con.close()


@needs_pg
def test_pgvector_ranks_like_memory(kb, pg_dsn):
    ids = [c.clause_id for c in kb._docs]
    pg = PgVectors(pg_dsn, kb.info.key, kb.embedder.name, kb._vectors, ids)
    for q in QUERIES:
        qv = kb.embedder.embed_query(q)
        assert pg.ranked(qv, 10)[:5] == kb._vector_store.ranked(qv, 10)[:5], q


@needs_pg
def test_hybrid_search_gives_the_same_hits_on_pgvector(ingested, pg_dsn, monkeypatch):
    memory_kb = PolicyKB.build(ingested)
    monkeypatch.setenv("CLAIMCLEAR_POLICY_KB_VECTORS", pg_dsn)
    pg_kb = PolicyKB.build(ingested)
    assert isinstance(pg_kb._vector_store, PgVectors)
    for q in QUERIES:
        assert [h.clause_id for h in pg_kb.search(q, k=5)] == [h.clause_id for h in memory_kb.search(q, k=5)], q


@needs_pg
def test_vectors_are_uploaded_once_and_again_only_when_they_change(kb, pg_dsn):
    ids = [c.clause_id for c in kb._docs]
    PgVectors(pg_dsn, kb.info.key, kb.embedder.name, kb._vectors, ids)
    store = PgVectors(pg_dsn, kb.info.key, kb.embedder.name, kb._vectors, ids)
    con = _connect(PG)
    cur = con.cursor()
    cur.execute(f"SELECT count(*), max(xmin::text::bigint) FROM {store.table}")
    count, first_xmin = cur.fetchone()
    assert count == len(ids)
    changed = [list(v) for v in kb._vectors]
    changed[0] = [-x for x in changed[0]]
    PgVectors(pg_dsn, kb.info.key, kb.embedder.name, changed, ids)
    cur.execute(f"SELECT count(*), max(xmin::text::bigint) FROM {store.table}")
    count2, second_xmin = cur.fetchone()
    con.close()
    assert count2 == len(ids) and second_xmin > first_xmin          # rewritten after the change


def test_bad_table_prefix_is_refused(kb):
    with pytest.raises(ValueError):
        PgVectors("postgresql://u:p@127.0.0.1:1/db?table_prefix=x;DROP", "W", "hashing", kb._vectors, ["1"])
