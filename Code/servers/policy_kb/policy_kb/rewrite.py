"""Query rewriting: from the policyholder's words to the wording's words.

People ask "why did they cut my medicine bill?"; the wording says "proportionate
deduction" and "pharmacy". Two rewriters, same interface (``str -> str``):

* ``GlossaryRewriter`` (default): adds policy terms for everyday phrases from a
  reviewed glossary. Deterministic, free and testable; the original words are
  kept, so nothing the user said is lost.
* ``LLMRewriter``: asks a model (Member 3's client factory) to restate the
  question in policy language. Pass any ``callable(prompt) -> str``.

The Recall@5 report compares search with and without rewriting, as the plan asks.
"""

from __future__ import annotations

import re
from typing import Callable, Protocol


class Rewriter(Protocol):
    name: str

    def __call__(self, query: str) -> str: ...


class NoRewriter:
    name = "none"

    def __call__(self, query: str) -> str:
        return query


# (pattern in the user's words, policy terms to add). Reviewed list; extend it as evaluation shows gaps.
GLOSSARY: list[tuple[str, str]] = [
    (r"\b(medicines?|drugs?|tablets?|pharmacy)\b", "pharmacy medicines drugs"),
    (r"\b(cut|cuts|reduced|reduce|less money|deducted|deduct\w*|took off|short paid|underpaid|paid less)\b",
     "deduction deducted"),
    (r"\b(proportion\w*|ratio|in the same proportion|percentage of (the )?bill)\b",
     "proportionate deduction associated medical expenses"),
    (r"\b(room|ward|bed)\b", "room rent room category eligible limit"),
    (r"\b(expensive|bigger|private|deluxe|suite|upgraded?) room\b", "room rent above eligible limit proportionate deduction"),
    (r"\b(tests?|scans?|x-?rays?|mri|ct|lab|blood tests?|investigations?)\b", "diagnostics investigation"),
    (r"\b(gloves?|masks?|caps?|consumables?|kit|registration)\b", "non-payable items consumables annexure"),
    (r"\b(eye|cataract|lens)\b", "cataract treatment per eye"),
    (r"\b(implants?|stents?|clips?|devices?|lens)\b", "implants medical devices"),
    (r"\b(waiting|wait|new policy|just bought|recently bought|renew\w*|first year)\b",
     "waiting period continuous coverage inception renewal"),
    (r"\b(old (illness|disease|problem)|existing (illness|disease|condition)|already had|before (the|my) policy)\b",
     "pre-existing disease"),
    (r"\b(co-?pay\w*|my share|pay part|portion i pay|5 ?%|five percent)\b", "co-payment percentage admissible claim"),
    (r"\b(complain\w*|complaint|unhappy|not satisfied|dispute|appeal|escalate)\b",
     "grievance redressal grievance officer ombudsman"),
    (r"\b(icu|intensive care|critical care)\b", "ICU charges intensive care unit"),
    (r"\bbefore (admission|hospitalisation|hospitalization|being admitted)\b", "pre-hospitalisation expenses"),
    (r"\bafter (discharge|being discharged|hospitalisation)\b", "post-hospitalisation expenses"),
    (r"\b(how long|time to settle|days to pay|delay\w*|late payment)\b", "settlement of claim days interest"),
    (r"\b(documents?|papers?|what to submit|bills? to send)\b", "documents for reimbursement claim form"),
    (r"\b(breakdown|break-up|itemi[sz]ed|why each|details of deduction)\b", "itemised breakdown statement deducted"),
    (r"\b(accident|injury|fell|road)\b", "accident"),
    (r"\b(nursing|nurse|doctor'?s? fees?|surgeon|operation theatre|ot charges)\b",
     "associated medical expenses nursing surgeon fees operation theatre"),
    (r"\b(ayurveda|homeopathy|unani|siddha|ayush)\b", "AYUSH treatment"),
    (r"\b(robotic|stem cell|modern treatment)\b", "modern treatment methods"),
    (r"\b(day ?care|same day|less than 24 hours)\b", "day care treatment"),
    (r"\b(limit|maximum|cap|capped|how much)\b", "limit maximum sum insured"),
]


class GlossaryRewriter:
    name = "glossary"

    def __init__(self, glossary: list[tuple[str, str]] = GLOSSARY):
        self._rules = [(re.compile(p, re.I), terms) for p, terms in glossary]

    def __call__(self, query: str) -> str:
        added = [terms for pattern, terms in self._rules if pattern.search(query)]
        return query if not added else f"{query} {' '.join(dict.fromkeys(added))}"


LLM_PROMPT = """Rewrite the policyholder's question as a short search query in the language of an Indian
health-insurance policy wording (Arogya Sanjeevani). Use policy terms such as "proportionate deduction",
"associated medical expenses", "room rent", "co-payment", "pre-existing disease", "waiting period",
"non-payable items", "pharmacy", "diagnostics", "grievance redressal". Keep the user's key facts.
Return only the query.

Question: {query}
Query:"""


class LLMRewriter:
    """Model-based rewriting. ``complete`` is any ``callable(prompt: str) -> str`` (e.g. a LangChain chat model
    wrapped as ``lambda p: llm.invoke(p).content``). The rewrite is added to, not substituted for, the query."""

    name = "llm"

    def __init__(self, complete: Callable[[str], str], prompt: str = LLM_PROMPT):
        self._complete = complete
        self._prompt = prompt

    def __call__(self, query: str) -> str:
        rewritten = (self._complete(self._prompt.format(query=query)) or "").strip()
        return f"{query} {rewritten}" if rewritten else query


class ChainRewriter:
    """Apply several rewriters in turn, e.g. the LLM first, then the glossary."""

    def __init__(self, *rewriters: Rewriter):
        self._rewriters = rewriters
        self.name = "+".join(r.name for r in rewriters)

    def __call__(self, query: str) -> str:
        for r in self._rewriters:
            query = r(query)
        return query


def openrouter_rewriter(model: str | None = None, client=None) -> LLMRewriter:
    """An ``LLMRewriter`` that calls an OpenRouter chat model (default ``openai/gpt-4.1-mini``,
    or ``$CLAIMCLEAR_REWRITE_MODEL``). Needs ``OPENROUTER_API_KEY`` when it runs."""
    import os

    from .openrouter import DEFAULT_CHAT_MODEL, shared_client

    chosen = model or os.environ.get("CLAIMCLEAR_REWRITE_MODEL") or DEFAULT_CHAT_MODEL
    rw = LLMRewriter(lambda prompt: (client or shared_client()).complete(prompt, chosen, temperature=0, max_tokens=80))
    rw.name = f"openrouter:{chosen}"
    return rw


def make_rewriter(name: str) -> Rewriter:
    """``none`` / ``glossary`` / ``openrouter[:model]`` / ``glossary+openrouter[:model]`` (LLM, then glossary)."""
    if name in ("", "none"):
        return NoRewriter()
    if name == "glossary":
        return GlossaryRewriter()
    if name.startswith("openrouter"):
        return openrouter_rewriter(name.split(":", 1)[1] if ":" in name else None)
    if name.startswith("glossary+openrouter"):
        rest = name.split("+", 1)[1]
        return ChainRewriter(openrouter_rewriter(rest.split(":", 1)[1] if ":" in rest else None), GlossaryRewriter())
    raise ValueError(f"unknown rewriter {name!r}")
