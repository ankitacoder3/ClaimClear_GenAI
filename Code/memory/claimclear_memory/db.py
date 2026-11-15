"""The database under the memory store: SQLite (one file, the default) or PostgreSQL (production).

    CLAIMCLEAR_MEMORY_DB=var/memory/memory.db                              # SQLite (default path)
    CLAIMCLEAR_MEMORY_DB=postgresql://user:password@host:5432/db           # PostgreSQL
    CLAIMCLEAR_MEMORY_DB=postgresql://user:password@host:5432/db?schema=memory   # its own schema

The store writes portable SQL (``?`` placeholders, ``INSERT ... ON CONFLICT``); the
PostgreSQL connection turns ``?`` into the driver's ``%s`` and returns rows that can be
read by name or position, as SQLite's are. The driver is ``pg8000`` (pure Python),
imported only when a PostgreSQL URL is used.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlparse


def is_postgres(target: Any) -> bool:
    return isinstance(target, str) and target.startswith(("postgresql://", "postgres://"))


class Row(tuple):
    """A result row readable by position and by column name, like ``sqlite3.Row``."""

    def __new__(cls, values: Sequence[Any], names: Sequence[str]):
        row = super().__new__(cls, values)
        row._names = {n: i for i, n in enumerate(names)}
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._names[key])
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._names)


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur
        self.rowcount = cur.rowcount

    def _names(self) -> list[str]:
        return [d[0] for d in (self._cur.description or [])]

    def fetchone(self) -> Optional[Row]:
        r = self._cur.fetchone()
        return None if r is None else Row(r, self._names())

    def fetchall(self) -> list[Row]:
        names = self._names()
        return [Row(r, names) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class _PgConnection:
    """The few ``sqlite3.Connection`` methods the store uses, on a pg8000 connection."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _PgCursor:
        cur = self._con.cursor()
        cur.execute(sql.replace("?", "%s"), tuple(params))
        return _PgCursor(cur)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self._con.cursor().execute(statement)

    def commit(self) -> None:
        self._con.commit()

    def rollback(self) -> None:
        self._con.rollback()

    def close(self) -> None:
        self._con.close()


class Database:
    """Opens connections to the configured database."""

    def __init__(self, target: str | Path):
        self.postgres = is_postgres(target)
        self.target = target if self.postgres else Path(target)
        self.schema = None
        if self.postgres:
            schema = parse_qs(urlparse(str(target)).query).get("schema", [None])[0]
            if schema and not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", schema):
                raise ValueError("schema must be lower-case letters, digits and underscores")
            self.schema = schema
        else:
            if str(self.target) == ":memory:":
                raise ValueError("use a file path; an in-memory SQLite database is lost between connections")
            self.target.parent.mkdir(parents=True, exist_ok=True)

    def _open(self):
        if not self.postgres:
            con = sqlite3.connect(self.target, timeout=10)
            con.row_factory = sqlite3.Row
            return con
        import pg8000.dbapi
        u = urlparse(str(self.target))
        raw = pg8000.dbapi.connect(user=unquote(u.username or ""), password=unquote(u.password or ""),
                                   host=u.hostname or "127.0.0.1", port=u.port or 5432,
                                   database=(u.path or "/").lstrip("/") or None)
        con = _PgConnection(raw)
        if self.schema:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            con.execute(f"SET search_path TO {self.schema}")
        return con

    @contextmanager
    def connect(self) -> Iterator[Any]:
        con = self._open()
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def has_table(self, con, name: str) -> bool:
        if self.postgres:
            sql = "SELECT 1 FROM information_schema.tables WHERE table_name = ? AND table_schema = current_schema()"
        else:
            sql = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
        return con.execute(sql, (name,)).fetchone() is not None
