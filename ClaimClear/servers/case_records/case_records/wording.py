"""Which policy wording a case is checked against, and whether to ask the user for theirs.

Users never have to upload their policy wording when ClaimClear already has it. The policy schedule
prints the wording's IRDAI UIN; the wording is chosen in this order:

1. ``selected`` / ``uploaded``: the app set one on the case (``CaseStore.set_wording``): a catalogue
   UIN the user picked, or ``upload:doc_...`` once their uploaded wording is indexed.
2. ``from_schedule``: the UIN printed on the policy schedule is in the reviewed catalogue
   (``development/dev_data/wordings/catalogue.json``): that wording, nothing to ask.
3. ``not_reviewed``: the schedule names a wording ClaimClear doesn't have. The standard Arogya
   Sanjeevani wording (the default) is used for now, and ``wording_needed`` is true: ask the user to
   upload their policy wording. If the case already holds a document with the role
   ``policy_wording``, ``wording_document_id`` names it, and the app indexes that instead of asking.
4. ``not_printed``: no schedule, or no UIN on it. The default wording is used; nothing is asked.

Only the schedule's visible text is read (hidden text is never trusted to choose a wording). A UIN
printed on a document can only pick a wording from the reviewed catalogue, never load anything else.
"""
# (Project restructuring #1)

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CATALOGUE_ENV = "CLAIMCLEAR_POLICY_CATALOGUE"
UIN_IN_TEXT = re.compile(r"\b[A-Z]{7}\d{5}V\d{6}\b")


def default_catalogue_path() -> Path:
    env = os.environ.get(CATALOGUE_ENV)
    return Path(env) if env else Path(__file__).resolve().parents[3] / "development" / "dev_data" / "wordings" / "catalogue.json"


def catalogue_uins(path: Optional[Path] = None) -> frozenset[str]:
    """The UINs of the reviewed wordings policy-kb serves (empty if the catalogue file is missing)."""
    p = path or default_catalogue_path()
    if not p.exists():
        return frozenset()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return frozenset(w["wording_uin"] for w in raw.get("wordings", []) if w.get("wording_uin"))


def uin_in(text: str) -> str:
    """The UIN a document prints most often ("" if none)."""
    found = Counter(UIN_IN_TEXT.findall(text or ""))
    return found.most_common(1)[0][0] if found else ""


@dataclass(frozen=True)
class WordingChoice:
    wording_uin: str               # pass to policy-kb; also what get_policy returns
    wording_source: str            # "catalogue" or "uploaded"
    status: str                    # selected | uploaded | from_schedule | not_reviewed | not_printed
    schedule_wording_uin: str      # as printed on the policy schedule ("" if none)
    wording_needed: bool           # ask the user for their policy wording
    wording_document_id: str       # a policy_wording document already in the case ("" if none)
    note: str                      # for the agent: what to tell or ask the user

    def as_dict(self) -> dict:
        return asdict(self)


def choose(case_wording: str, default_uin: str, schedule_text: Optional[str], catalogue: frozenset[str],
           wording_document_id: str = "") -> WordingChoice:
    """Decide the case's wording (see the module docstring)."""
    printed = uin_in(schedule_text or "")
    if case_wording.startswith("upload:"):
        return WordingChoice(case_wording, "uploaded", "uploaded", printed, False, wording_document_id,
                             "The user's own uploaded policy wording is used (not reviewed by ClaimClear: "
                             "limits are the standard Arogya Sanjeevani ones).")
    if case_wording:
        note = "The wording the user selected is used."
        if printed and printed != case_wording:
            note += f" The policy schedule prints a different UIN ({printed}): confirm with the user."
        return WordingChoice(case_wording, "catalogue", "selected", printed, False, wording_document_id, note)
    if printed and printed in catalogue:
        return WordingChoice(printed, "catalogue", "from_schedule", printed, False, wording_document_id,
                             f"The policy schedule names wording {printed}, which ClaimClear has reviewed.")
    if printed:
        ask = (f"The case already has a policy wording document ({wording_document_id}): index it "
               "(the app's upload step) instead of asking." if wording_document_id else
               "Ask the user to upload their policy wording (the document with the policy's terms and "
               "conditions); they can also continue without it.")
        return WordingChoice(default_uin, "catalogue", "not_reviewed", printed, True, wording_document_id,
                             f"The policy schedule names wording {printed}, which ClaimClear has not reviewed. "
                             f"Until the user's wording is uploaded, the standard Arogya Sanjeevani wording "
                             f"({default_uin}) and its limits are used; say so in the answer. {ask}")
    return WordingChoice(default_uin, "catalogue", "not_printed", "", False, wording_document_id,
                         "The policy schedule prints no wording UIN: the standard Arogya Sanjeevani wording "
                         f"({default_uin}) is used. If the user has their policy wording, they can upload it.")
