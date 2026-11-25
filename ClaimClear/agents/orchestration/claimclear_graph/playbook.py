"""The playbook (E3): short lessons from dev and red-team failures, added to a step's prompt when they apply.

``CLAIMCLEAR_PLAYBOOK=on`` turns it on (default off, so results stay comparable); ``CLAIMCLEAR_PLAYBOOK_FILE``
picks another lessons file (default ``playbook.json`` next to this file). A lesson is used when its ``step``
matches, it is not ``rejected``, and it has no keywords or one of them appears in the case's text. Lessons change
what a model reads or says, never the engine's arithmetic.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

DEFAULT_FILE = Path(__file__).with_name("playbook.json")


def enabled() -> bool:
    return os.environ.get("CLAIMCLEAR_PLAYBOOK", "off").strip().lower() in ("on", "1", "true", "yes")


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, ...]:
    return tuple(json.loads(Path(path).read_text(encoding="utf-8")).get("lessons", []))


def lessons(step: str, text: str = "") -> list[dict]:
    """The lessons for ``step`` that apply to a case whose text is ``text`` (empty when the playbook is off)."""
    if not enabled():
        return []
    low = text.lower()
    return [l for l in _load(os.environ.get("CLAIMCLEAR_PLAYBOOK_FILE") or str(DEFAULT_FILE))
            if l.get("step") == step and l.get("status") != "rejected"
            and (not l.get("keywords") or any(k.lower() in low for k in l["keywords"]))]


def block(step: str, text: str = "") -> str:
    """The prompt block for ``step`` ("" when nothing applies)."""
    found = lessons(step, text)
    if not found:
        return ""
    return "Lessons from earlier cases (follow them):\n" + "\n".join(f"- {l['do']}" for l in found) + "\n\n"
