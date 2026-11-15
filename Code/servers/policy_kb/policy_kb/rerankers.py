"""Rerankers: re-score the top candidates by reading the query and each clause together.

* ``NoReranker``: keeps the fused order (default; no download).
* ``FastEmbedReranker``: a cross-encoder through ``fastembed``; default
  ``Xenova/ms-marco-MiniLM-L-6-v2`` (about 80 MB, downloaded on first use).
"""

from __future__ import annotations

from typing import Optional, Protocol


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, texts: list[str]) -> Optional[list[float]]: ...


class NoReranker:
    name = "none"

    def rerank(self, query: str, texts: list[str]) -> Optional[list[float]]:
        return None  # keep the fused order


class FastEmbedReranker:
    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2", cache_dir: str | None = None):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = f"fastembed:{model}"
        self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)

    def rerank(self, query: str, texts: list[str]) -> Optional[list[float]]:
        return [float(s) for s in self._model.rerank(query, texts)]


def make_reranker(name: str) -> Reranker:
    """``none`` / ``fastembed`` / ``fastembed:<model>``."""
    if name in ("", "none"):
        return NoReranker()
    if name.startswith("fastembed"):
        model = name.split(":", 1)[1] if ":" in name else "Xenova/ms-marco-MiniLM-L-6-v2"
        return FastEmbedReranker(model)
    raise ValueError(f"unknown reranker {name!r}")
