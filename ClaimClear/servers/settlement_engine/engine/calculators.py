"""One pure function per policy rule.

Each function takes plain values and returns plain values, so it can be unit
tested on its own. ``engine.compute_settlement`` calls them in the order the
wording requires and turns their results into deductions and facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from .categories import service_words
from .identifiers import same_policy
from .models import BillLine, ConditionType, LineView, PastClaim, Policy, PolicyRules
from .money import D, ZERO, add_months, months_completed, pct_of, round_paise

# --------------------------------------------------------------------------- daily caps


def room_cap_per_day(rules: PolicyRules, sum_insured: Decimal) -> Decimal:
    """Lower of ``room_pct_of_si`` % of sum insured and ``room_max_inr``.

    SI ₹3,00,000 -> min(₹6,000, ₹5,000) = ₹5,000.
    """
    return min(pct_of(rules.room_pct_of_si, sum_insured), rules.room_max_inr)


def icu_cap_per_day(rules: PolicyRules, sum_insured: Decimal) -> Decimal:
    """Lower of ``icu_pct_of_si`` % of sum insured and ``icu_max_inr``."""
    return min(pct_of(rules.icu_pct_of_si, sum_insured), rules.icu_max_inr)


def excess_over_cap(rate_per_day: Decimal, days: Decimal, cap_per_day: Decimal) -> Decimal:
    """Rupees above the daily cap: ``max(0, rate - cap) x days``.

    3 days at ₹7,000 with a ₹5,000 cap -> ₹6,000.
    """
    return max(ZERO, D(rate_per_day) - D(cap_per_day)) * D(days)


def gst_on(amount: Decimal, gst_pct: Decimal) -> Decimal:
    """GST at ``gst_pct`` % on ``amount`` (unrounded)."""
    return pct_of(gst_pct, amount)


# --------------------------------------------------------------------------- proportionate deduction


def proportionate_deduction(linked_total: Decimal, eligible_room: Decimal, actual_room: Decimal) -> Decimal:
    """Cut on associated expenses when the room was above the cap.

    ``linked_total x (actual_room - eligible_room) / actual_room``, which is the
    same as ``linked_total x (1 - eligible/actual)`` without a repeating
    fraction. Worked example: ₹74,900 x (21,000 - 15,000) / 21,000 = ₹21,400.

    ``eligible_room`` and ``actual_room`` are room-rent totals over the stay
    (rate x days), so a mid-stay room change is weighted by days.
    """
    linked_total, eligible_room, actual_room = D(linked_total), D(eligible_room), D(actual_room)
    if actual_room <= 0 or eligible_room >= actual_room:
        return ZERO
    return linked_total * (actual_room - eligible_room) / actual_room


# --------------------------------------------------------------------------- co-pay


def copay(admissible: Decimal, copay_pct: Decimal) -> Decimal:
    """Co-pay on the admissible amount, rounded to paise. Applied after every other deduction."""
    return round_paise(pct_of(copay_pct, admissible))


# --------------------------------------------------------------------------- policy period and sum insured


def duplicate_lines(lines: Iterable[LineView], raw: dict[str, BillLine]) -> dict[str, str]:
    """Lines that repeat an earlier line: ``{duplicate_line_id: first_line_id}``.

    A duplicate has the same category, the same date (or both undated), the same amount with
    GST, and names the same service (``service_words``). The same service on another day is a
    daily charge, not a duplicate.
    """
    first: dict[tuple, str] = {}
    out: dict[str, str] = {}
    for v in lines:
        key = (v.category, raw[v.line_id].date, D(v.amount) + D(v.gst), service_words(v.description))
        if key in first:
            out[v.line_id] = first[key]
        else:
            first[key] = v.line_id
    return out


def in_policy_period(policy: Policy, day: date) -> bool:
    return policy.period_start <= day <= policy.period_end


def claims_in_period(policy: Policy, history: Iterable[PastClaim], exclude_claim_id: str = "") -> list[PastClaim]:
    """Settled claims on this policy whose admission falls in the current policy period.

    Claims from other policy years never count, which is what keeps sub-limits
    from mixing years.
    """
    return [
        c for c in history
        if same_policy(c.policy_no, policy.policy_no)
        and c.status.lower() == "settled"
        and c.claim_id != exclude_claim_id
        and in_policy_period(policy, c.admission)
    ]


def same_hospitalisation_settled(claim, history: Iterable[PastClaim]) -> Optional[PastClaim]:
    """An earlier settled claim on this policy for the same hospitalisation, or ``None``.

    The same hospitalisation: the same admission date and, when both name one, a diagnosis that shares
    a word. Only a hospital bill counts (it has an admission and a discharge date); a pharmacy or
    post-hospitalisation bill for the same stay is a separate expense.
    """
    if claim.admission is None or claim.discharge is None:
        return None
    said = _diagnosis_words(claim.diagnosis)
    for c in history:
        if (same_policy(c.policy_no, claim.policy_no) and c.status.lower() == "settled"
                and c.claim_id != claim.claim_id and c.admission == claim.admission):
            other = _diagnosis_words(c.diagnosis)
            if not said or not other or said & other:
                return c
    return None


_DIAGNOSIS_STOP = frozenset({"acute", "chronic", "with", "and", "of", "the", "left", "right", "fever", "disease"})


def _diagnosis_words(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _DIAGNOSIS_STOP)


def remaining_sum_insured(policy: Policy, history: Iterable[PastClaim], exclude_claim_id: str = "") -> Decimal:
    """Sum insured minus what was already paid this policy period (never below zero)."""
    used = sum((c.settled_amount for c in claims_in_period(policy, history, exclude_claim_id)), ZERO)
    return max(ZERO, policy.sum_insured - used)


# --------------------------------------------------------------------------- cataract


_CATARACT = re.compile(r"\b(cataract|phaco\w*)\b", re.I)
_BOTH_EYES = re.compile(r"\b(both eyes?|bilateral)\b", re.I)
_RIGHT_EYE = re.compile(r"\bright\b", re.I)
_LEFT_EYE = re.compile(r"\bleft\b", re.I)


def is_cataract(*texts: str) -> bool:
    return any(_CATARACT.search(t or "") for t in texts)


def eyes_treated(*texts: str) -> Optional[frozenset[str]]:
    """``{"right"}``, ``{"left"}``, ``{"right", "left"}``, or ``None`` if the text doesn't say."""
    joined = " ".join(t or "" for t in texts)
    if _BOTH_EYES.search(joined):
        return frozenset({"right", "left"})
    eyes = set()
    if _RIGHT_EYE.search(joined):
        eyes.add("right")
    if _LEFT_EYE.search(joined):
        eyes.add("left")
    return frozenset(eyes) or None


def cataract_limit_per_eye(rules: PolicyRules, sum_insured: Decimal) -> Decimal:
    """Lower of ``cataract_pct_of_si`` % of sum insured and ``cataract_max_inr``.

    SI ₹2,00,000 -> min(₹50,000, ₹40,000) = ₹40,000.
    """
    return min(pct_of(rules.cataract_pct_of_si, sum_insured), rules.cataract_max_inr)


def cataract_used_this_period(policy: Policy, history: Iterable[PastClaim], eye: str, exclude_claim_id: str = "") -> Decimal:
    """Amount already paid for cataract on ``eye`` in the current policy period.

    Uses ``settled_amount``. Whether the sub-limit is consumed by the amount
    paid or by the admissible amount before co-pay is a verdict-policy decision
    for Member 1; change it here if they decide otherwise.
    """
    used = ZERO
    for c in claims_in_period(policy, history, exclude_claim_id):
        if not is_cataract(c.diagnosis, c.procedure):
            continue
        eyes = eyes_treated(c.diagnosis, c.procedure)
        if eyes and eye in eyes:
            used += c.settled_amount / len(eyes)
    return used


# --------------------------------------------------------------------------- waiting periods


@dataclass(frozen=True)
class WaitingResult:
    """Outcome of the waiting-period check.

    ``served`` is True, False, or None when the condition type is needed to decide.
    """

    served: Optional[bool]
    rule_ref: str
    days_since_inception: int
    months_since_inception: int
    required: str
    reason: str


# Conditions the standard Arogya Sanjeevani wording lists with a specific waiting
# period. A starting list only: replace it with the list in the ingested wording.
LISTED_ILLNESS_PATTERN = re.compile(
    r"\b(cataract|hernia|hydrocele|fistula|fissure|piles|haemorrhoids?|hemorrhoids?|sinusitis|"
    r"tonsil\w*|adenoid\w*|mastoid\w*|tympanoplasty|hysterectomy|polyps?|cysts?|benign|"
    r"gall ?bladder|gallstones?|cholelithiasis|calculus|calculi|kidney stones?|renal stones?|"
    r"ureteric|urolithiasis|gout|rheumat\w*|joint replacement|joints?|menisc\w*|osteoarthritis|"
    r"osteoporosis|arthritis|disc prolapse|prolapsed (intervertebral )?disc|varicose)\b",
    re.I,
)


# The two lists of the wording's specific waiting period (Code Excl02): which list a condition is on
# decides whether the shorter (24 months) or longer (36 or 48 months, by insurer) wait applies.
# Only conditions the lists name outright: a word like "joint" alone could be on either.
LONG_LIST_PATTERN = re.compile(
    r"\b(joint replacement|(knee|hip|shoulder) replacement|arthroplasty|osteoarthritis|osteoporosis)\b", re.I)
SHORT_LIST_PATTERN = re.compile(
    r"\b(cataract|hernia\w*|hernioplasty|herniorrhaphy|hydrocele|fistula|fissures?|piles|haemorrhoids?|"
    r"hemorrhoids?|sinusitis|pilonidal|tonsil\w*|adenoid\w*|mastoid\w*|tympanoplasty|hysterectomy|polyps?|"
    r"cysts?|benign|gout|rheumatism|gall ?bladder|gallstones?|cholelithiasis|cholecyst\w*|calculus|calculi|"
    r"kidney stones?|renal stones?|ureteric|urolithiasis|varicose|(gastric|duodenal|peptic) ulcers?|"
    r"prostat\w* hypertrophy|disc prolapse|prolapsed (intervertebral )?disc)\b", re.I)


def listed_illness_tier(*texts: str) -> Optional[ConditionType]:
    """The waiting-period list that names the condition, or ``None`` if neither list names it outright."""
    if any(LONG_LIST_PATTERN.search(t or "") for t in texts):
        return ConditionType.LISTED_ILLNESS_LONG
    if any(SHORT_LIST_PATTERN.search(t or "") for t in texts):
        return ConditionType.LISTED_ILLNESS_SHORT
    return None


def looks_listed_illness(*texts: str) -> bool:
    """Keyword check: does the diagnosis or procedure name a listed illness?"""
    return any(LISTED_ILLNESS_PATTERN.search(t or "") for t in texts)


def waiting_period(
    rules: PolicyRules,
    first_inception: date,
    admission: date,
    condition: Optional[ConditionType],
    listed_by_keyword: bool = False,
) -> WaitingResult:
    """Check the waiting periods, always counted from **first inception**, never from the latest renewal.

    Rules:
      * Accidents have no waiting period.
      * Any illness is excluded if admitted fewer than ``initial_waiting_days`` days after first inception.
      * Listed illnesses and pre-existing diseases need the full months, i.e. admission on or after
        first inception + N calendar months.
      * If ``condition`` is not given:
          - cover longer than every waiting period -> served, whatever the condition is;
          - the diagnosis names a listed illness (``listed_by_keyword``) -> served if cover is longer
            than the longest listed-illness period, not served if shorter than the shortest, and
            undecided (``served=None``) in between, because the tier isn't known;
          - otherwise -> treated as an ordinary illness. A pre-existing disease is never assumed:
            it applies only when ``condition`` is ``PRE_EXISTING``.
    """
    days = (admission - first_inception).days
    months = months_completed(first_inception, admission)
    initial_ok = days >= rules.initial_waiting_days
    longest = max(rules.listed_illness_waiting_months + (rules.pre_existing_waiting_months,))
    shortest_listed = min(rules.listed_illness_waiting_months)
    longest_listed = max(rules.listed_illness_waiting_months)

    if condition == ConditionType.ACCIDENT:
        return WaitingResult(True, "initial_waiting_period", days, months, "none for accidents",
                             "Accidents have no waiting period.")

    if not initial_ok:
        if condition is None:
            return WaitingResult(None, "initial_waiting_period", days, months,
                                 f"{rules.initial_waiting_days} days",
                                 f"Admitted {days} days after first inception, inside the "
                                 f"{rules.initial_waiting_days}-day initial waiting period, unless it was an accident.")
        return WaitingResult(False, "initial_waiting_period", days, months,
                             f"{rules.initial_waiting_days} days",
                             f"Admitted {days} days after first inception, inside the "
                             f"{rules.initial_waiting_days}-day initial waiting period.")

    if condition == ConditionType.ILLNESS:
        return WaitingResult(True, "initial_waiting_period", days, months,
                             f"{rules.initial_waiting_days} days",
                             f"Initial {rules.initial_waiting_days}-day waiting period served ({days} days).")

    if condition in (ConditionType.LISTED_ILLNESS_SHORT, ConditionType.LISTED_ILLNESS_LONG, ConditionType.PRE_EXISTING):
        if condition == ConditionType.PRE_EXISTING:
            needed, ref = rules.pre_existing_waiting_months, "pre_existing_waiting_period"
        else:
            idx = 0 if condition == ConditionType.LISTED_ILLNESS_SHORT else -1
            needed, ref = rules.listed_illness_waiting_months[idx], "listed_illness_waiting_period"
        served = admission >= add_months(first_inception, needed)
        verb = "served" if served else "not served"
        return WaitingResult(served, ref, days, months, f"{needed} months",
                             f"{needed}-month waiting period {verb}: {months} full months of cover since first inception.")

    # condition not given, initial period served
    if admission >= add_months(first_inception, longest):
        return WaitingResult(True, "listed_illness_waiting_period", days, months, f"{longest} months (longest)",
                             f"{months} full months of cover since first inception, longer than every "
                             f"waiting period ({longest} months at most), so none applies.")
    if listed_by_keyword:
        if admission >= add_months(first_inception, longest_listed):
            return WaitingResult(True, "listed_illness_waiting_period", days, months, f"{longest_listed} months",
                                 f"The diagnosis is a listed illness. {months} full months of cover since first "
                                 f"inception, longer than the longest listed-illness waiting period ({longest_listed} months).")
        if admission < add_months(first_inception, shortest_listed):
            return WaitingResult(False, "listed_illness_waiting_period", days, months, f"{shortest_listed} months",
                                 f"The diagnosis is a listed illness. Only {months} full months of cover since first "
                                 f"inception, shorter than the shortest listed-illness waiting period ({shortest_listed} months).")
        return WaitingResult(None, "listed_illness_waiting_period", days, months,
                             f"{shortest_listed} or {longest_listed} months",
                             f"The diagnosis is a listed illness and there are {months} full months of cover since "
                             f"first inception. Whether the {shortest_listed}- or {longest_listed}-month waiting "
                             "period applies depends on which list it is on.")
    return WaitingResult(True, "initial_waiting_period", days, months, f"{rules.initial_waiting_days} days",
                         f"Initial {rules.initial_waiting_days}-day waiting period served ({days} days). The "
                         "diagnosis is not on the listed-illness table and no pre-existing disease was stated.")
