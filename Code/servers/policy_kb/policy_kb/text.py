"""Tokenising for BM25 and the hashing embedder: lower-case, split, drop stop words, light stemming.

Deliberately simple and deterministic. Insurance wording is formal English, so a
light suffix stemmer ("deductions" -> "deduction", "charged" -> "charg") is enough
to match a user's words to the wording's.
"""

from __future__ import annotations

import re

TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")

STOP_WORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her
here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not
now of off on once only or other our ours ourselves out over own same she should so some such than that the
their theirs them themselves then there these they this those through to too under until up very was we were
what when where which while who whom why will with would you your yours yourself yourselves shall may such
""".split())


def stem(word: str) -> str:
    """A light English suffix stripper, so that charge / charges / charged all become ``charg``.

    Numbers and words of three letters or fewer are unchanged.
    """
    w = word
    if w.isdigit() or len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) >= 5:
        w = w[:-3] + "y"
    elif w.endswith(("sses", "xes", "zes", "ches", "shes")):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) >= 4:
        w = w[:-1]
    if w.endswith("ing") and len(w) >= 6:
        w = w[:-3]
    elif w.endswith("ed") and len(w) >= 5:
        w = w[:-2]
    if w.endswith("e") and len(w) >= 5:
        w = w[:-1]
    return w


def tokens(text: str, keep_stop_words: bool = False) -> list[str]:
    """Stemmed tokens of ``text``. ``2%`` and ``Rs. 5,000`` become ``2`` and ``5000``."""
    text = (text or "").lower().replace(",", "")
    out = []
    for t in TOKEN.findall(text):
        t = t.strip(".'")
        if not t or (not keep_stop_words and t in STOP_WORDS):
            continue
        out.append(stem(t))
    return out
