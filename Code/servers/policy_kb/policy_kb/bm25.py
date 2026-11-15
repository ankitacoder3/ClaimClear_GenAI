"""Okapi BM25, the keyword half of hybrid search.

Implemented here (about 40 lines) instead of depending on ``rank-bm25``, so the
package installs anywhere, including Python versions without third-party wheels.
Same formula and defaults as ``rank_bm25.BM25Okapi`` (k1 = 1.5, b = 0.75).
"""

from __future__ import annotations

import math
from collections import Counter

from .text import tokens


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        df: Counter = Counter()
        for c in self.docs:
            df.update(c.keys())
        n = len(self.docs)
        # BM25+ style floor keeps idf positive for terms in most documents
        self.idf = {t: max(0.01, math.log((n - f + 0.5) / (f + 0.5) + 1)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for c, length in zip(self.docs, self.lengths):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / max(self.avg_len, 1e-9))
            for t in q:
                f = c.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out
