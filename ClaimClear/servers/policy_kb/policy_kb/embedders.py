"""Embedders: turn text into vectors for the semantic half of hybrid search.

Two implementations behind one small interface:

* ``HashingEmbedder``: deterministic feature hashing of words, word pairs and
  character n-grams. No download, no dependencies, works offline and in CI.
  It captures spelling variants and shared phrases, not meaning. Use it for
  tests and as a fallback.
* ``FastEmbedEmbedder``: a real sentence-embedding model through ``fastembed``
  (ONNX, no PyTorch); default ``BAAI/bge-small-en-v1.5``, the plan's choice. The
  model is downloaded from Hugging Face on first use (about 70 MB), so it needs
  approval and network once.

Vectors are plain lists of floats, L2-normalised, so cosine similarity is a dot product.
"""

from __future__ import annotations

import math
import zlib
from typing import Protocol

from .text import tokens


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class HashingEmbedder:
    """Signed feature hashing (crc32, so it is the same in every process)."""

    def __init__(self, dims: int = 1024):
        self.dims = dims
        self.name = f"hashing-{dims}"

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = tokens(text)
        feats = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:])]
        for w in words:
            padded = f"#{w}#"
            feats += [(f"c:{padded[i:i + 4]}", 0.3) for i in range(max(1, len(padded) - 3))]
        return feats

    def _embed(self, text: str) -> list[float]:
        v = [0.0] * self.dims
        for feat, weight in self._features(text):
            h = zlib.crc32(feat.encode())
            v[h % self.dims] += weight if (h >> 16) & 1 else -weight
        return _normalise([math.copysign(math.log1p(abs(x)), x) for x in v])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FastEmbedEmbedder:
    """A sentence-embedding model via ``fastembed``. Install ``fastembed`` and allow the model download first."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", cache_dir: str | None = None):
        from fastembed import TextEmbedding  # imported here so the package works without it

        self.name = f"fastembed:{model}"
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_normalise([float(x) for x in v]) for v in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return _normalise([float(x) for x in next(iter(self._model.query_embed([text])))])


class OpenRouterEmbedder:
    """Embeddings through OpenRouter's API (no local model). Default ``baai/bge-m3``.

    The API key is only needed when something is embedded, so an index built with
    this embedder can still be loaded for keyword search and clause lookup without it.
    """

    def __init__(self, model: str | None = None, client=None):
        import os

        from .openrouter import DEFAULT_EMBEDDING_MODEL

        self.model = model or os.environ.get("CLAIMCLEAR_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        self.name = f"openrouter:{self.model}"
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from .openrouter import shared_client
            self._client = shared_client()
        return self._client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_normalise(v) for v in self.client.embed(texts, self.model)]

    def embed_query(self, text: str) -> list[float]:
        return _normalise(self.client.embed([text], self.model)[0])


def make_embedder(name: str) -> Embedder:
    """``hashing`` / ``hashing-<dims>`` / ``openrouter`` / ``openrouter:<model>`` / ``fastembed`` / ``fastembed:<model>``."""
    if name.startswith("hashing"):
        dims = int(name.split("-", 1)[1]) if "-" in name else 1024
        return HashingEmbedder(dims)
    if name.startswith("openrouter"):
        return OpenRouterEmbedder(name.split(":", 1)[1] if ":" in name else None)
    if name.startswith("fastembed"):
        model = name.split(":", 1)[1] if ":" in name else "BAAI/bge-small-en-v1.5"
        return FastEmbedEmbedder(model)
    raise ValueError(f"unknown embedder {name!r}")
