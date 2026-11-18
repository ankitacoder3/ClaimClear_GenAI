"""Helpers shared by the agent modules: hashing, tool-error exits, citations, concurrency, look-alikes."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Awaitable, Iterable

from claimclear_contracts import identifiers
from claimclear_tools.results import ClaimClearToolError

from ..state import OUTCOME_TOOL_ERROR

# Engine questions ``claimclear_tools.apply_answer`` can write into the claim. Others (Q-TIE-..., Q-POLICY-PERIOD)
# need another document or the insurer, so they are reported in the explanation instead of asked.
ANSWERABLE = ("Q-ROOM-PRICING", "Q-CONDITION-TYPE", "Q-EYE", "Q-ADMISSION")

DISCLAIMER = ("ClaimClear explains your settlement against your policy wording. It is guidance, not a "
              "decision: only the insurer, the ombudsman or a court can change what is paid.")


def sha256(text: str) -> str:
    """SHA-256 of the exact text (no stripping: the insurer-portal server hashes the raw text)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stop(exc: ClaimClearToolError, who: str, outcome: str = OUTCOME_TOOL_ERROR) -> dict:
    """End the run on a tool error, with the toolkit's suggested action as the route."""
    info = exc.info
    return {"outcome": outcome, "route": info.action,
            "trace": [f"{who}: {info.tool} returned {info.code} -> {info.action} ({info.message[:160]})"]}


def cite(clause: dict) -> str:
    c = clause.get("citation")
    return c if isinstance(c, str) and c else f"clause {clause.get('clause_id', '?')}"


def lookalike_policy_no(printed: str, real: str) -> bool:
    """The same policy number once look-alike characters are mapped: a spoofed print, not another policy.

    Uses ``claimclear_contracts.identifiers``, the engine's own table shipped in the contracts (a contracts
    test keeps the two identical), so it works without the servers' source on disk."""
    return bool(printed and printed != real and identifiers.same_policy(printed, real)
                and identifiers.has_lookalikes(printed))


async def gather_calls(calls: Iterable[Awaitable[Any]]) -> list[Any]:
    """Run independent tool calls concurrently (one MCP session serves many requests at once).

    Results come back in call order; the first ``ClaimClearToolError`` is raised after all calls finish,
    so no call is left running."""
    results = await asyncio.gather(*calls, return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return results
