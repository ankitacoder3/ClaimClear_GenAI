"""Assembling tool arguments, and applying the policyholder's answers.

The settlement-engine tools take ``case = {"claim", "policy", "history"}``.
``claim`` comes from the document reader; ``policy`` and ``history`` come
unchanged from case-records. When the engine asks a question
(``status == "needs_information"``), the answer is written into ``claim`` and the
engine is called again; ``apply_answer`` does that for every question it can ask.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Optional

CONDITION_TYPES = ("accident", "illness", "listed_illness_short", "listed_illness_long", "pre_existing")
EYES = ("right", "left", "both")


def build_case(claim: dict, policy: dict, history: Optional[Iterable[dict]] = None) -> dict:
    """The ``case`` argument for every settlement-engine tool.

    Checks the one thing that is easy to get wrong when assembling it: that the
    claim, the policy and the history all refer to the same policy number.
    """
    history = list(history or [])
    policy_no = policy.get("policy_no")
    if claim.get("policy_no") != policy_no:
        raise ValueError(f"claim.policy_no {claim.get('policy_no')!r} != policy.policy_no {policy_no!r}")
    other = sorted({h.get("policy_no") for h in history} - {policy_no})
    if other:
        raise ValueError(f"history contains other policies: {other}")
    return {"claim": claim, "policy": policy, "history": history}


def _line_categories(settlement: Optional[dict], line_ids: Iterable[str]) -> list[str]:
    lines = {line["line_id"]: line for line in (settlement or {}).get("lines", [])}
    return sorted({lines[i]["category"] for i in line_ids if i in lines})


def _iso(value: Any) -> str:
    """A date answer as YYYY-MM-DD; raises ValueError for anything else."""
    import datetime as dt
    if isinstance(value, dt.date):
        return value.isoformat()
    return dt.date.fromisoformat(str(value)).isoformat()


def apply_answer(claim: dict, question: dict, answer: Any, settlement: Optional[dict] = None) -> dict:
    """Return a new claim with the policyholder's answer to one engine question applied.

    =================  =============================================  ===================================
    question_id        answer                                         effect on the claim
    =================  =============================================  ===================================
    Q-ROOM-PRICING     ``bool`` (applies to every category asked      ``room_priced_by_category[cat]``
                       about) or ``{category: bool}``
    Q-CONDITION-TYPE   one of ``CONDITION_TYPES``                     ``condition_type``
    Q-EYE              ``"right"``, ``"left"`` or ``"both"``          appended to ``diagnosis``
    Q-ADMISSION        ``{"admission": date, "discharge": date}``      ``admission``, ``discharge``
                       or one ISO date (admission; discharge the same
                       day unless the claim has one)
    Q-POLICY-PERIOD    —                                              can't be answered in the claim:
                                                                      load the right policy schedule
    =================  =============================================  ===================================

    ``settlement`` (the ``expected_settlement`` result that asked) is needed for a
    ``bool`` answer to Q-ROOM-PRICING, to know which categories the question is about.
    """
    qid = question.get("question_id", "")
    new = copy.deepcopy(claim)
    if qid == "Q-ROOM-PRICING":
        if isinstance(answer, dict):
            updates = {str(k): bool(v) for k, v in answer.items()}
        else:
            cats = _line_categories(settlement, question.get("line_ids", []))
            if not cats:
                raise ValueError("pass the settlement that asked, or answer with {category: bool}")
            updates = {c: bool(answer) for c in cats}
        new.setdefault("room_priced_by_category", {}).update(updates)
        return new
    if qid == "Q-CONDITION-TYPE":
        if answer not in CONDITION_TYPES:
            raise ValueError(f"answer must be one of {CONDITION_TYPES}")
        new["condition_type"] = answer
        return new
    if qid == "Q-EYE":
        if answer not in EYES:
            raise ValueError(f"answer must be one of {EYES}")
        eye = "both eyes" if answer == "both" else f"{answer} eye"
        new["diagnosis"] = f"{new.get('diagnosis', '')}, {eye}".strip(", ")
        return new
    if qid == "Q-ADMISSION":
        dates = answer if isinstance(answer, dict) else {"admission": answer}
        admission = _iso(dates.get("admission"))
        discharge = _iso(dates.get("discharge") or new.get("discharge") or admission)
        if discharge < admission:
            raise ValueError("discharge is before admission")
        new["admission"], new["discharge"] = admission, discharge
        return new
    if qid == "Q-POLICY-PERIOD":
        raise ValueError("this question needs the policy schedule for the admission year, not a change to the claim")
    raise ValueError(f"unknown question {qid!r}")
