"""Guard models on OpenRouter (same key as the chat model). One class, three models:

* ``safeguard``  openai/gpt-oss-safeguard-20b: "bring your own policy"; given our product summary and misuse classes
* ``llamaguard`` meta-llama/llama-guard-4-12b: the course brief's suggestion; fixed harm categories
* ``nemotron``   nvidia/nemotron-3.5-content-safety: content-safety classifier (fixed categories)

Each model has its own prompt and output format, handled by a small adapter.
"""
from __future__ import annotations

import os
import re

from .input_guard import InputGuard, Finding
from .policy import CLASSES, FOR_KIND, policy

OPENROUTER_URL = "https://openrouter.ai/api/v1"
MODELS = {"safeguard": "openai/gpt-oss-safeguard-20b", "llamaguard": "meta-llama/llama-guard-4-12b",
          "nemotron": "nvidia/nemotron-3.5-content-safety"}


def model_for(key: str) -> str:
    """The guard's model: ``CLAIMCLEAR_GUARD_MODEL_<KEY>`` (e.g. CLAIMCLEAR_GUARD_MODEL_SAFEGUARD) when set, else the
    default above. The safeguard guard sends our written policy, so any instruction-following model can stand in."""
    return os.environ.get(f"CLAIMCLEAR_GUARD_MODEL_{key.upper()}") or MODELS[key]

SAFEGUARD_FORMAT = """

Classify the content below against this policy. Answer with exactly one line:
VIOLATION: <class> : <the offending words, copied exactly, at most 160 characters>
where <class> is one of: {classes}
or
SAFE"""

VIOLATION = re.compile(r"VIOLATION\s*:\s*([a-z_ ]+?)\s*:\s*(.+)", re.I)
NEMOTRON = re.compile(r'"?user safety"?\s*:\s*"?(unsafe|safe)', re.I)
NEMOTRON_CATS = re.compile(r'"?safety categories"?\s*:\s*"?([^"\n}]+)', re.I)


class OpenRouterGuard(InputGuard):
    handles_long_text = False

    def __init__(self, key: str, max_chars: int = 8000):
        super().__init__()
        self.name, self.model, self.max_chars = key, model_for(key), max_chars
        self._chat = None

    def chat(self):
        if self._chat is None:
            from langchain_openai import ChatOpenAI
            self._chat = ChatOpenAI(model=self.model, base_url=OPENROUTER_URL, temperature=0, max_tokens=2000,   # room for reasoning
                                    api_key=os.environ.get("OPENROUTER_API_KEY", ""), timeout=60)
        return self._chat

    def messages(self, text: str, kind: str = "document") -> list:
        if self.name == "safeguard":
            return [("system", policy(kind) + SAFEGUARD_FORMAT.format(classes=", ".join(FOR_KIND[kind]))),
                    ("user", text)]
        return [("user", text)]                               # Llama Guard / Nemotron classify the user turn

    def parse(self, reply: str, text: str) -> tuple[bool, str, str, str]:
        """(flagged, snippet, reason, category) from the model's reply."""
        r = (reply or "").strip()
        if self.name == "safeguard":
            m = VIOLATION.search(r)
            if not m:
                return False, "", "", ""
            cat = m.group(1).strip().lower().replace(" ", "_")
            cat = cat if cat in CLASSES else "injection"
            return True, m.group(2).strip().strip('"')[:200], cat.replace("_", " "), cat
        if self.name == "llamaguard":
            if r.lower().startswith("unsafe"):
                return True, text[:160], f"unsafe content ({' '.join(r.split()[1:]) or 'unsafe'})", "injection"
            return False, "", "", ""
        m = NEMOTRON.search(r)                                 # nemotron's JSON-like reply
        flagged = (m.group(1).lower() == "unsafe") if m else r.lower().startswith("unsafe")
        cats = NEMOTRON_CATS.search(r)
        return (True, text[:160], f"unsafe content ({cats.group(1).strip() if cats else 'unspecified'})", "injection") \
            if flagged else (False, "", "", "")

    async def check(self, text: str, kind: str, where: str) -> list[Finding]:
        if not (text or "").strip():
            return []
        if not os.environ.get("OPENROUTER_API_KEY"):
            return self.failed(RuntimeError("no OPENROUTER_API_KEY"))
        try:
            reply = await self.chat().ainvoke(self.messages(text[:self.max_chars], kind))
        except Exception as exc:               # a guard model being down never stops the chat; it is counted
            return self.failed(exc)
        content = (getattr(reply, "content", "") or "").strip()
        if not content:                        # a reasoning model that never answered: unknown, not "safe"
            return self.failed(RuntimeError("empty reply (the model spent its budget on reasoning)"))
        flagged, snippet, reason, category = self.parse(content, text)
        return [Finding(self.name, where, snippet, reason, category)] if flagged else []
