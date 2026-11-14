"""Verdict labels and the only wording an explanation may use for each.

The labels are the settlement-engine's ``Verdict`` values (a test checks them
against the exported tool schemas). The wording comes from the plan: never
"the insurer cheated you", never "you will get this back".
"""

from __future__ import annotations

from typing import Literal

Verdict = Literal["matches_policy", "does_not_match_policy", "not_verifiable", "method_matches"]
VERDICTS: tuple[str, ...] = ("matches_policy", "does_not_match_policy", "not_verifiable", "method_matches")

# does_not_match_policy splits by the sign of the row's difference (insurer amount - policy amount).
VERDICT_WORDING: dict[str, str] = {
    "matches_policy": "matches your policy",
    "does_not_match_policy+": "may be disputable",
    "does_not_match_policy-": "the insurer deducted less than your policy allows",
    "method_matches": "worked out correctly, but on the insurer's figures",
    "not_verifiable": "we can't check this without more information",
}

# Phrases no explanation may contain, whatever the verdict.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "cheated", "fraud by the insurer", "you will get", "you will definitely", "guaranteed", "you will win",
)


def wording_for(row: dict) -> str:
    """The phrase the explanation may use for a row's verdict (a reproduce_deduction / audit row)."""
    verdict = row.get("verdict", "")
    if verdict == "does_not_match_policy":
        return VERDICT_WORDING["does_not_match_policy+" if (row.get("difference") or 0) > 0 else "does_not_match_policy-"]
    return VERDICT_WORDING.get(verdict, VERDICT_WORDING["not_verifiable"])


def may_offer_grievance(row: dict) -> bool:
    """A grievance is offered only for rows that don't match the policy and cost the policyholder money."""
    return row.get("verdict") == "does_not_match_policy" and (row.get("difference") or 0) > 0
