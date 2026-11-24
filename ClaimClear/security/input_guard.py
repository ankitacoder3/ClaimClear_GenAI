"""The input-guard interface: every guard checks one piece of input text (a document channel or a chat message)
and returns findings (empty when clean). Other kinds of security check live in their own modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Finding:
    guard: str        # which guard found it: rules, llm, safeguard, llamaguard, nemotron
    where: str        # "bill.pdf: visible text", "bill.pdf: page2.hidden_text", "chat"
    snippet: str      # the offending text, as found (for the user and for redaction)
    reason: str       # what it tries to do, in plain words
    category: str = "injection"   # security.policy.CLASSES: injection, phishing, fraud_help, false_claim, ...

    def line(self) -> str:
        return f'{self.where}: {self.category}: {self.reason} ("{self.snippet[:120]}")'


class InputGuard:
    """``check(text, kind, where)``: ``kind`` is "document" or "chat"; ``where`` names the source for the findings."""
    name = "base"
    handles_long_text = True          # False: only short text is sent (cost); long documents get the cheap guards

    def __init__(self):
        self.errors: list[str] = []   # checks that could not run (a failed check finds nothing, so count them)

    def failed(self, exc: Exception) -> list[Finding]:
        self.errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
        return []

    async def check(self, text: str, kind: str, where: str) -> list[Finding]:
        raise NotImplementedError
