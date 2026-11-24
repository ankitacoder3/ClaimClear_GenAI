"""Layer 1, keywords: phrases ordinary bills, letters, policies and policyholder questions do not contain.
Free, instant and predictable; brittle against rewording, so the model guards back it up."""
from __future__ import annotations

import re

from .input_guard import InputGuard, Finding

RULES = [(re.compile(p, re.I | re.M), why) for p, why in [
    (r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all|your|the)\b.{0,20}"
     r"\b(instructions?|rules?|prompts?|guidelines?)", "asks to ignore the assistant's instructions"),
    (r"\[\s*(system|assistant|developer|admin)\b[^\]]{0,40}\]", "fake system or assistant tag"),
    (r"^\s*(system|assistant|developer)\s*(prompt)?\s*:", "fake system or assistant turn"),
    (r"\b(you are now|from now on,? you|act as (an?|the)|pretend (to be|you are)|your new (role|instructions?))\b",
     "tries to change the assistant's role"),
    (r"\b(system prompt|developer mode|jailbreak)\b", "talks about the assistant's prompt or modes"),
    (r"\b(note|notice|message|instructions?)s? (to|for) (any |all )?(the )?(ai|assistant|model|llm|chatbot|claimclear|"
     r"automated|automatic|machine)\b", "a note addressed to software"),
    (r"\breport (all|every|each) (deductions?|items?|rows?|charges?) as (correct|valid|payable|fine)\b",
     "dictates the verdict to report"),
    (r"\b(do not|don't|never) (tell|mention|show|reveal|disclose)\b.{0,30}\b(user|customer|policyholder|patient)\b",
     "asks to hide something from the user"),
    (r"\b(tell|inform|assure) (this|the) (customer|user|policyholder|patient)\b", "dictates what to tell the user"),
    (r"\b(i am|i'm|this is)\b.{0,15}\b(from|with) (the )?.{0,30}\b(claims (team|department)|insurer|insurance company|"
     r"tpa|support team|admin)\b", "claims to speak for the insurer or staff"),
]]


class RulesGuard(InputGuard):
    name = "rules"

    async def check(self, text: str, kind: str, where: str) -> list[Finding]:
        out = []
        for pattern, why in RULES:
            m = pattern.search(text or "")
            if m:
                line = next((ln for ln in (text[max(0, m.start() - 200):m.end() + 200]).splitlines()
                             if m.group(0)[:20].lower() in ln.lower()), m.group(0))
                out.append(Finding(self.name, where, " ".join(line.split())[:200], why))
        return out
