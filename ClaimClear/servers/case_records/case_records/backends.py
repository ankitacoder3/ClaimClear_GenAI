"""Where the case store keeps its index and its files.

Two pieces, each with a development default and a production backend:

=================  ==========================  =============================================
Piece              Default (development)       Production
=================  ==========================  =============================================
Index              ``index.json`` in the root  PostgreSQL (``CLAIMCLEAR_CASE_INDEX``)
Files (blobs)      ``files/`` in the root      MinIO or any S3 store (``CLAIMCLEAR_BLOB_STORE``)
=================  ==========================  =============================================

::

    CLAIMCLEAR_CASE_INDEX=postgresql://user:password@host:5432/db
    CLAIMCLEAR_BLOB_STORE=s3://bucket?endpoint=host:9000&secure=0&prefix=case-store/
    CLAIMCLEAR_S3_ACCESS_KEY=...   CLAIMCLEAR_S3_SECRET_KEY=...     (never in the URL)

``CaseStore`` keeps the same API whatever the backends: the index holds the same
records (no original file names), and files keep their neutral names.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional, Protocol
from urllib.parse import parse_qs, unquote, urlparse

INDEX_ENV = "CLAIMCLEAR_CASE_INDEX"
BLOB_ENV = "CLAIMCLEAR_BLOB_STORE"
S3_KEY_ENV = ("CLAIMCLEAR_S3_ACCESS_KEY", "CLAIMCLEAR_S3_SECRET_KEY")


class Index(Protocol):
    def load(self) -> tuple[list[dict], list[dict]]:
        """``(documents, cases)`` as dicts."""

    def save(self, documents: list[dict], cases: list[dict]) -> None: ...


class Blobs(Protocol):
    def put(self, name: str, data: bytes, media_type: str) -> None: ...

    def get(self, name: str) -> Optional[bytes]:
        """The stored bytes, or None when missing."""

    def path(self, name: str) -> Optional[Path]:
        """A local path when the backend has one (development), else None."""


# --------------------------------------------------------------------------- development defaults


class JsonIndex:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.file = self.root / "index.json"

    def load(self) -> tuple[list[dict], list[dict]]:
        if not self.file.exists():
            return [], []
        raw = json.loads(self.file.read_text(encoding="utf-8"))
        return raw.get("documents", []), raw.get("cases", [])

    def save(self, documents: list[dict], cases: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"documents": documents, "cases": cases}, fh, indent=2)
        for attempt in range(50):        # Windows: replacing fails while another process is reading the file
            try:
                os.replace(tmp, self.file)
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.05)


class LocalBlobs:
    def __init__(self, root: Path):
        self.dir = Path(root) / "files"

    def put(self, name: str, data: bytes, media_type: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_bytes(data)

    def get(self, name: str) -> Optional[bytes]:
        p = self.dir / name
        return p.read_bytes() if p.exists() else None

    def path(self, name: str) -> Optional[Path]:
        return self.dir / name


# --------------------------------------------------------------------------- production


def connect_postgres(dsn: str):
    """A DB-API connection (pg8000, pure Python) from ``postgresql://user:password@host:port/db``."""
    import pg8000.dbapi
    u = urlparse(dsn)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError("expected a postgresql:// URL")
    return pg8000.dbapi.connect(user=unquote(u.username or ""), password=unquote(u.password or ""),
                                host=u.hostname or "127.0.0.1", port=u.port or 5432,
                                database=(u.path or "/").lstrip("/") or None)


class PostgresIndex:
    """The same records as index.json, one row per document and per case (JSON text, upserted).

    ``?table_prefix=`` on the URL (default ``case_store_``) keeps separate stores, e.g. per test run.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        prefix = parse_qs(urlparse(dsn).query).get("table_prefix", ["case_store_"])[0]
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", prefix):
            raise ValueError("table_prefix must be lower-case letters, digits and underscores")
        self.docs_table, self.cases_table = f"{prefix}documents", f"{prefix}cases"
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(f"CREATE TABLE IF NOT EXISTS {self.docs_table} (document_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
            cur.execute(f"CREATE TABLE IF NOT EXISTS {self.cases_table} (case_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
            con.commit()

    def _conn(self):
        return _Closing(connect_postgres(self.dsn))

    def load(self) -> tuple[list[dict], list[dict]]:
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(f"SELECT record FROM {self.docs_table} ORDER BY document_id")
            docs = [json.loads(r[0]) for r in cur.fetchall()]
            cur.execute(f"SELECT record FROM {self.cases_table} ORDER BY case_id")
            cases = [json.loads(r[0]) for r in cur.fetchall()]
        return docs, cases

    def save(self, documents: list[dict], cases: list[dict]) -> None:
        with self._conn() as con:
            cur = con.cursor()
            for d in documents:
                cur.execute(f"INSERT INTO {self.docs_table} VALUES (%s, %s) ON CONFLICT (document_id) "
                            "DO UPDATE SET record = EXCLUDED.record", (d["document_id"], json.dumps(d)))
            for c in cases:
                cur.execute(f"INSERT INTO {self.cases_table} VALUES (%s, %s) ON CONFLICT (case_id) "
                            "DO UPDATE SET record = EXCLUDED.record", (c["case_id"], json.dumps(c)))
            con.commit()


class S3Blobs:
    """Files in a MinIO (or any S3) bucket under neutral names. The bucket is created if missing."""

    def __init__(self, url: str, access_key: Optional[str] = None, secret_key: Optional[str] = None):
        from minio import Minio
        u = urlparse(url)
        if u.scheme != "s3" or not u.netloc:
            raise ValueError("expected s3://bucket?endpoint=host:port")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.bucket = u.netloc
        self.prefix = q.get("prefix", "case-store/")
        self.client = Minio(q.get("endpoint", "127.0.0.1:9000"),
                            access_key=access_key or os.environ.get(S3_KEY_ENV[0], ""),
                            secret_key=secret_key or os.environ.get(S3_KEY_ENV[1], ""),
                            secure=q.get("secure", "1") not in ("0", "false"))
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, name: str, data: bytes, media_type: str) -> None:
        self.client.put_object(self.bucket, self.prefix + name, io.BytesIO(data), len(data), content_type=media_type)

    def get(self, name: str) -> Optional[bytes]:
        from minio.error import S3Error
        try:
            resp = self.client.get_object(self.bucket, self.prefix + name)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return None
            raise
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def path(self, name: str) -> Optional[Path]:
        return None


class _Closing:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *exc):
        self.con.close()


# --------------------------------------------------------------------------- choice


def index_for(root: Path) -> Index:
    dsn = os.environ.get(INDEX_ENV, "").strip()
    return PostgresIndex(dsn) if dsn else JsonIndex(root)


def blobs_for(root: Path) -> Blobs:
    url = os.environ.get(BLOB_ENV, "").strip()
    return S3Blobs(url) if url else LocalBlobs(root)
