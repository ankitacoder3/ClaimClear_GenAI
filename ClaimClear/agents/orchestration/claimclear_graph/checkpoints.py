"""Durable checkpoints, so a case paused at a question or at the approval gate survives a restart.

    async with open_checkpointer("sqlite:///var/graph/checkpoints.db") as saver:
        graph = build_claimclear_graph(services, checkpointer=saver)

==========================================  ===============================================================
``url`` (or ``$CLAIMCLEAR_CHECKPOINTS``)      Saver
==========================================  ===============================================================
unset, ``memory``                           ``MemorySaver``: in process only (tests, demos)
``sqlite:///path/to/file.db``, ``*.db``      ``AsyncSqliteSaver`` (``langgraph-checkpoint-sqlite``, installed)
``postgresql://user:pw@host/db``            ``AsyncPostgresSaver`` (``pip install langgraph-checkpoint-postgres``)
==========================================  ===============================================================

Resuming after a restart needs nothing special: rebuild the graph with a saver on the same store and use the
same ``thread_id``; ``HumanApprovalGateway`` then finds the pause where it was left.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

ENV = "CLAIMCLEAR_CHECKPOINTS"


@asynccontextmanager
async def open_checkpointer(url: Optional[str] = None) -> AsyncIterator[BaseCheckpointSaver]:
    """A checkpointer for ``url`` (default ``$CLAIMCLEAR_CHECKPOINTS``, else in memory), closed on exit."""
    url = url if url is not None else os.environ.get(ENV, "")
    if not url or url == "memory":
        yield MemorySaver()
        return
    if url.startswith(("postgresql://", "postgres://")):
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("PostgreSQL checkpoints need: pip install langgraph-checkpoint-postgres") from exc
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            yield saver
        return
    path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else url
    if not (url.startswith("sqlite:") or path.endswith((".db", ".sqlite", ".sqlite3"))):
        raise ValueError(f"{ENV}: expected memory, sqlite:///file.db or postgresql://..., got {url!r}")
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        yield saver
