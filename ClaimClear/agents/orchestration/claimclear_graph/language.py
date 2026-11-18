"""Rewriting the explanation into plain language, or into another language, with an LLM (optional).

    from langchain_openai import ChatOpenAI
    services = Services(toolkit=tk, rewriter=llm_rewriter(ChatOpenAI(model=..., temperature=0)), language="hi")

The model only changes the words. The critic then checks the rewritten text it produced: every ₹ amount must
still be one a tool produced (written exactly, with the ₹ sign and digits), and no forbidden phrase may appear.
A rewrite that changes, drops into words, or invents an amount fails, and the user gets the plain verdict table
instead. The English sentences stay in ``draft`` as the source of truth.
"""

from __future__ import annotations

from typing import Any

LANGUAGES = {"en": "plain, simple English", "hi": "simple Hindi", "mr": "simple Marathi", "ta": "simple Tamil",
             "te": "simple Telugu", "bn": "simple Bengali", "kn": "simple Kannada", "gu": "simple Gujarati"}

PROMPT = ("Rewrite the explanation below in {language} for a policyholder with no insurance knowledge. Rules:\n"
          "1. Keep every rupee amount EXACTLY as written, with the ₹ sign and digits (for example ₹8,522.86). "
          "Never round, add, remove or convert an amount, and never write an amount in words.\n"
          "2. Keep row labels (R1, R2, COPAY) and clause numbers (C.1, E.28.3) unchanged.\n"
          "3. Add no facts, advice or promises. Never say the policyholder will get money back.\n"
          "4. Return only the rewritten text.\n\n<explanation>\n{text}\n</explanation>")


def llm_rewriter(llm: Any):
    """A ``Rewriter`` from any LangChain chat model."""

    async def rewrite(text: str, language: str) -> str:
        msg = await llm.ainvoke(PROMPT.format(language=LANGUAGES.get(language, language), text=text))
        out = getattr(msg, "content", msg)
        if isinstance(out, list):
            out = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in out)
        return str(out).strip()

    return rewrite
