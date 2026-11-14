"""Where clause vectors live, and how the vector half of hybrid search is ranked.

* ``MemoryVectors`` (default): the vectors in the index file, ranked in Python.
* ``PgVectors``: the vectors in PostgreSQL with the pgvector extension, ranked by the
  database (``ORDER BY embedding <#> query``, the negative inner product, which equals
  cosine on these normalised vectors). Chosen with::

      CLAIMCLEAR_POLICY_KB_VECTORS=postgresql://user:password@host:5432/db

  The table ``policy_kb_vectors`` holds one row per clause per wording and embedder;
  ``policy_kb_vector_sets`` records a fingerprint of each set, so an index is uploaded
  once and re-uploaded only when its vectors change.

BM25, Reciprocal Rank Fusion and the reranker are unchanged: only where the vector
ranking is computed moves.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional, Protocol
from urllib.parse import parse_qs, unquote, urlparse

VECTORS_ENV = "CLAIMCLEAR_POLICY_KB_VECTORS"


class VectorStore(Protocol):
    def ranked(self, query_vector: list[float], top: int) -> list[int]:
        """Indices of the indexed clauses, best match first, at most ``top``."""


class MemoryVectors:
    def __init__(self, vectors: list[list[float]]):
        self.vectors = vectors

    def ranked(self, query_vector: list[float], top: int) -> list[int]:
        scores = [sum(x * y for x, y in zip(query_vector, v)) for v in self.vectors]
        return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top]


def _connect(dsn: str):
    import pg8000.dbapi
    u = urlparse(dsn)
    return pg8000.dbapi.connect(user=unquote(u.username or ""), password=unquote(u.password or ""),
                                host=u.hostname or "127.0.0.1", port=u.port or 5432,
                                database=(u.path or "/").lstrip("/") or None)


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def fingerprint(embedder: str, vectors: list[list[float]], clause_ids: list[str]) -> str:
    h = hashlib.sha256(embedder.encode())
    h.update(json.dumps(clause_ids).encode())
    for v in vectors:
        h.update(_literal(v).encode())
    return h.hexdigest()


class PgVectors:
    """Clause vectors in PostgreSQL + pgvector. ``?table_prefix=`` on the URL keeps a separate set of tables."""

    def __init__(self, dsn: str, wording: str, embedder: str, vectors: list[list[float]], clause_ids: list[str]):
        if not vectors:
            raise ValueError("no vectors to store")
        self.dsn = dsn
        self.wording, self.embedder = wording, embedder
        self.dims = len(vectors[0])
        prefix = parse_qs(urlparse(dsn).query).get("table_prefix", ["policy_kb_"])[0]
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", prefix):
            raise ValueError("table_prefix must be lower-case letters, digits and underscores")
        self.table, self.sets = f"{prefix}vectors", f"{prefix}vector_sets"
        self._sync(vectors, clause_ids)

    def _sync(self, vectors: list[list[float]], clause_ids: list[str]) -> None:
        fp = fingerprint(self.embedder, vectors, clause_ids)
        con = _connect(self.dsn)
        try:
            cur = con.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"CREATE TABLE IF NOT EXISTS {self.sets} (wording TEXT, embedder TEXT, dims INT NOT NULL, "
                        "fingerprint TEXT NOT NULL, PRIMARY KEY (wording, embedder))")
            cur.execute(f"CREATE TABLE IF NOT EXISTS {self.table} (wording TEXT, embedder TEXT, doc_index INT, "
                        f"clause_id TEXT NOT NULL, embedding vector NOT NULL, PRIMARY KEY (wording, embedder, doc_index))")
            cur.execute(f"SELECT fingerprint FROM {self.sets} WHERE wording = %s AND embedder = %s",
                        (self.wording, self.embedder))
            row = cur.fetchone()
            if row is None or row[0] != fp:
                cur.execute(f"DELETE FROM {self.table} WHERE wording = %s AND embedder = %s", (self.wording, self.embedder))
                for i, (v, cid) in enumerate(zip(vectors, clause_ids)):
                    cur.execute(f"INSERT INTO {self.table} VALUES (%s, %s, %s, %s, %s::vector)",
                                (self.wording, self.embedder, i, cid, _literal(v)))
                cur.execute(f"INSERT INTO {self.sets} VALUES (%s, %s, %s, %s) ON CONFLICT (wording, embedder) "
                            "DO UPDATE SET dims = EXCLUDED.dims, fingerprint = EXCLUDED.fingerprint",
                            (self.wording, self.embedder, self.dims, fp))
            con.commit()
        finally:
            con.close()

    def ranked(self, query_vector: list[float], top: int) -> list[int]:
        con = _connect(self.dsn)
        try:
            cur = con.cursor()
            cur.execute(f"SELECT doc_index FROM {self.table} WHERE wording = %s AND embedder = %s "
                        f"ORDER BY embedding <#> %s::vector, doc_index LIMIT %s",
                        (self.wording, self.embedder, _literal(query_vector), top))
            return [r[0] for r in cur.fetchall()]
        finally:
            con.close()


def vector_store_for(wording: str, embedder: str, vectors: list[list[float]], clause_ids: list[str],
                     dsn: Optional[str] = None) -> VectorStore:
    """``PgVectors`` when ``CLAIMCLEAR_POLICY_KB_VECTORS`` (or ``dsn``) is set, else ``MemoryVectors``."""
    dsn = dsn if dsn is not None else os.environ.get(VECTORS_ENV, "").strip()
    if dsn and vectors:
        return PgVectors(dsn, wording, embedder, vectors, clause_ids)
    return MemoryVectors(vectors)
