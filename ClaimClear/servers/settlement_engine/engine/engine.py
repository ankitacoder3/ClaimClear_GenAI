"""``compute_settlement``: what the policy wording says should be paid.

Order of operations (each step uses the result of the one before):

  1. Read every bill line: category, GST, non-payable flag.
  2. Claimed amount = line amounts + line GST - hospital discount. Check it against the printed total.
  2b. Document integrity: definite inconsistencies on the bill (impossible dates, more room days than the
     stay, a malformed hospital GSTIN, ...) are reported as ``integrity`` facts, never deducted. Impossible
     dates stop the computation and ask for the real ones.
  3. Policy period: the admission must fall inside the policy period on record. A bill with no
     admission date (a pharmacy or post-hospitalisation bill) asks for it and skips steps 3-4.
     A hospitalisation an earlier settled claim already paid is not paid again.
  4. Waiting periods, counted from first inception. Not served -> whole claim not admissible.
  5. Non-payable items (line amount + its GST), then lines billed twice for the same day, then
     bills dated outside the pre/post-hospitalisation days, then road ambulance above its limit.
  6. Room-rent cap per day, and the GST on the excess.
  7. ICU cap per day, and the GST on the excess.
  8. Proportionate deduction on associated expenses only, if the room was above the cap.
  9. Cataract sub-limit per eye, net of what was used earlier this policy period.
 10. Admissible = claimed - deductions 5-9.
 11. Co-pay on the admissible amount.
 12. Payable = admissible - co-pay, capped at the sum insured left this policy period.

Every reported figure is rounded to paise. Later steps use the rounded figures,
as a settlement letter does.

The engine never guesses. When it needs a fact it doesn't have (an unknown line
that the proportionate deduction would touch, an unknown condition type inside a
waiting period, an admission outside the policy period, an unstated eye), it
returns ``Status.NEEDS_INFORMATION`` with questions and no payable figure.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from . import calculators as calc
from . import integrity
from datetime import timedelta

from .categories import annexure_list, categorise, looks_non_payable, room_linked
from .identifiers import same_policy
from .models import (
    Category,
    Claim,
    Deduction,
    DeductionKind,
    Fact,
    LineView,
    PastClaim,
    Policy,
    PolicyRules,
    Question,
    SettlementResult,
    Status,
)
from .money import D, ZERO, round_paise

TOTAL_TOLERANCE = D(1)  # ₹1, the same tolerance the matcher uses


def _inr(value: Decimal) -> str:
    """₹ with Indian digit grouping, for formulas and fact text: 128350 -> ₹1,28,350."""
    value = round_paise(value)
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}" + ("" if frac == "00" else f".{frac}")


def _num(value: Decimal) -> str:
    """Plain number for formulas: 7000 -> 7,000 (no ₹)."""
    return _inr(value).replace("₹", "")


class _Builder:
    """Collects deductions, facts and questions with stable IDs."""

    def __init__(self) -> None:
        self.deductions: list[Deduction] = []
        self.facts: list[Fact] = []
        self.questions: list[Question] = []
        self.warnings: list[str] = []

    def fact(self, fact_id: str, kind: str, text: str, amount: Optional[Decimal] = None, *,
             formula: str = "", rule_ref: str = "", line_ids: tuple[str, ...] = (), **inputs) -> Fact:
        f = Fact(fact_id, kind, text, None if amount is None else round_paise(amount),
                 formula, rule_ref, line_ids, inputs)
        self.facts.append(f)
        return f

    def deduct(self, deduction_id: str, kind: DeductionKind, amount: Decimal, description: str, *,
               formula: str, rule_ref: str, line_ids: tuple[str, ...] = ()) -> Optional[Deduction]:
        amount = round_paise(amount)
        if amount <= 0:
            return None
        fact_id = "F-" + deduction_id
        self.fact(fact_id, "deduction", description, amount, formula=formula, rule_ref=rule_ref,
                  line_ids=line_ids, deduction_kind=kind.value)
        d = Deduction(deduction_id, kind, amount, description, formula, rule_ref, line_ids, fact_id)
        self.deductions.append(d)
        return d

    def ask(self, question_id: str, text: str, reason: str, line_ids: tuple[str, ...] = ()) -> None:
        if not any(q.question_id == question_id for q in self.questions):
            self.questions.append(Question(question_id, text, reason, line_ids))

    def deducted(self) -> Decimal:
        return sum((d.amount for d in self.deductions), ZERO)


# --------------------------------------------------------------------------- step 1


def read_lines(claim: Claim) -> list[LineView]:
    """Categorise every line and decide whether it is non-payable."""
    views = []
    for line in claim.lines:
        if line.category is not None:
            category, cat_source = line.category, "input"
        else:
            category, cat_source = categorise(line.description)
        if line.non_payable is not None:
            non_payable, np_source = bool(line.non_payable), "input"
        elif looks_non_payable(line.description, category):
            non_payable, np_source = True, "keyword"
        else:
            non_payable, np_source = False, "default"
        views.append(LineView(
            line_id=line.line_id,
            description=line.description,
            amount=D(line.amount),
            gst=line.gst,
            category=category,
            category_source=cat_source,
            non_payable=non_payable,
            non_payable_source=np_source,
            room_linked=room_linked(category, claim.room_priced_by_category),
        ))
    return views


# --------------------------------------------------------------------------- main entry point


def compute_settlement(
    claim: Claim,
    policy: Policy,
    rules: PolicyRules,
    history: Iterable[PastClaim] = (),
) -> SettlementResult:
    """Work out the settlement the policy wording requires for ``claim``."""
    history = list(history)
    b = _Builder()
    lines = read_lines(claim)
    raw = {line.line_id: line for line in claim.lines}
    si = D(policy.sum_insured)

    # 2. claimed amount -------------------------------------------------------------
    line_sum = sum((v.amount for v in lines), ZERO)
    gst_sum = sum((v.gst for v in lines), ZERO)
    discount = D(claim.discount)
    claimed = round_paise(line_sum + gst_sum - discount)
    formula = f"lines {_num(line_sum)} + GST {_num(gst_sum)}"
    if discount:
        formula += f" - discount {_num(discount)}"
    b.fact("F-CLAIMED", "claimed_amount", f"Amount claimed: {_inr(claimed)}", claimed,
           formula=formula, line_sum=line_sum, gst=gst_sum, discount=discount)
    if claim.printed_total is not None and abs(D(claim.printed_total) - claimed) > TOTAL_TOLERANCE:
        b.warnings.append(
            f"Bill lines add up to {_inr(claimed)} but the printed total is {_inr(D(claim.printed_total))}.")
        b.fact("F-TOTAL-MISMATCH", "warning",
               f"Bill lines add up to {_inr(claimed)}, printed total is {_inr(D(claim.printed_total))}",
               D(claim.printed_total) - claimed, printed_total=D(claim.printed_total))
    if claim.policy_no != policy.policy_no and same_policy(claim.policy_no, policy.policy_no):
        b.warnings.append(f"The bill prints the policy number as '{claim.policy_no}', with look-alike characters; "
                          f"it was matched to policy {policy.policy_no}.")
    for v in lines:
        if v.category == Category.UNKNOWN and not v.non_payable:
            b.warnings.append(f"Line {v.line_id} ('{v.description}') was not recognised; treated as payable.")

    # 2b. document integrity (engine/integrity.py): reported, never deducted ----------
    findings = integrity.check(claim, lines)
    for f in findings:
        b.fact(f"F-INTEGRITY-{f.code.upper().replace('_', '-')}", "integrity", f"{f.heading}: {f.text}",
               line_ids=f.line_ids, rule_ref="fraud", code=f.code, definite=f.definite, **f.inputs)
        b.warnings.append(f"{f.heading}: {f.text}.")
    if any(f.code == "discharge_before_admission" for f in findings):
        b.ask("Q-ADMISSION",
              f"The bill gives a discharge date ({claim.discharge.isoformat()}) before the admission date "
              f"({claim.admission.isoformat()}). What were the real admission and discharge dates? (The hospital's "
              "discharge summary shows them.)",
              "Every limit counted in days, and the waiting periods, depend on the dates of the stay.")
        return _finish(claim, b, lines, claimed, rules, policy, history)

    # 3. policy period --------------------------------------------------------------
    if claim.admission is None:
        b.ask("Q-ADMISSION",
              "This bill gives no admission date. When was the patient admitted to hospital, and discharged, "
              "for the treatment this bill belongs to? (For a pharmacy or post-hospitalisation bill, give the "
              "dates of the hospital stay it follows.)",
              "The policy period, the waiting periods and post-hospitalisation cover all depend on the "
              "admission date.")
    elif not calc.in_policy_period(policy, claim.admission):
        b.ask("Q-POLICY-PERIOD",
              f"The admission on {claim.admission.isoformat()} is outside the policy period on record "
              f"({policy.period_start.isoformat()} to {policy.period_end.isoformat()}). "
              "Can you share the policy schedule for the year of the admission?",
              "Sum insured, sub-limits and earlier claims depend on the policy year.")

    # 3b. the same hospitalisation settled under an earlier claim -------------------
    if claim.admission is not None:
        earlier = calc.same_hospitalisation_settled(claim, history)
        if earlier is not None:
            b.deduct("D-ALREADY-SETTLED", DeductionKind.ALREADY_SETTLED, claimed,
                     f"Whole claim not payable: the hospitalisation admitted on {claim.admission.isoformat()} was "
                     f"already settled under claim {earlier.claim_id} ({_inr(earlier.settled_amount)} paid)",
                     formula=f"claimed {_num(claimed)}", rule_ref="expenses_actually_incurred")
            return _finish(claim, b, lines, claimed, rules, policy, history, not_admissible=True)

    # 4. waiting periods ------------------------------------------------------------
    if claim.admission is None:
        return _rest(claim, policy, rules, history, b, lines, raw, claimed, si)
    condition, condition_source = claim.condition_type, "input" if claim.condition_type else "default"
    if condition is None:
        condition = calc.listed_illness_tier(claim.diagnosis, claim.procedure)
        if condition is not None:
            condition_source = "keyword"
    listed = condition is None and calc.looks_listed_illness(claim.diagnosis, claim.procedure)
    if listed:
        condition_source = "keyword"
    wait = calc.waiting_period(rules, policy.first_inception, claim.admission, condition, listed)
    b.fact("F-WAITING", "waiting_period", wait.reason, rule_ref=wait.rule_ref,
           first_inception=policy.first_inception, admission=claim.admission,
           days_since_inception=wait.days_since_inception,
           months_since_inception=wait.months_since_inception,
           required=wait.required, served=wait.served,
           condition_type=condition.value if condition else None,
           condition_source=condition_source)
    if wait.served is None:
        if wait.rule_ref == "initial_waiting_period":
            text = "Was this hospitalisation caused by an accident?"
        else:
            text = ("Which waiting-period list does the policy put this condition on? "
                    "(The insurer's letter or the policy's list of specific illnesses will say.)")
        b.ask("Q-CONDITION-TYPE", text, wait.reason)
    elif wait.served is False:
        b.deduct("D-WAITING", DeductionKind.WAITING_PERIOD, claimed,
                 f"Whole claim not admissible: {wait.reason}",
                 formula=f"claimed {_num(claimed)}", rule_ref=wait.rule_ref)
        return _finish(claim, b, lines, claimed, rules, policy, history, not_admissible=True)
    return _rest(claim, policy, rules, history, b, lines, raw, claimed, si)


def _line_ids(views: list[LineView]) -> tuple[str, ...]:
    return tuple(v.line_id for v in views)


def _rest(claim: Claim, policy: Policy, rules: PolicyRules, history: list[PastClaim], b: _Builder,
          lines: list[LineView], raw: dict, claimed: Decimal, si: Decimal) -> SettlementResult:
    """Steps 5-12: the deductions that don't depend on dates, then the totals."""
    # 5. non-payable items ----------------------------------------------------------
    for v in lines:
        if v.non_payable:
            listed_in = annexure_list(v.description)
            b.deduct(f"D-NONPAY-{v.line_id}", DeductionKind.NON_PAYABLE, v.amount + v.gst,
                     f"Non-payable item: {v.description}" + (f" (Annexure A {listed_in})" if listed_in else ""),
                     formula=f"{_num(v.amount)}" + (f" + GST {_num(v.gst)}" if v.gst else ""),
                     rule_ref="non_payable_items", line_ids=(v.line_id,))

    payable_lines = [v for v in lines if not v.non_payable]

    # 5b. the same charge billed twice for the same day ------------------------------
    duplicates = calc.duplicate_lines(payable_lines, raw)
    for v in payable_lines:
        if v.line_id in duplicates:
            first = raw[duplicates[v.line_id]]
            b.deduct(f"D-DUPLICATE-{v.line_id}", DeductionKind.DUPLICATE_LINE, v.amount + v.gst,
                     f"Charged twice: '{v.description}' repeats '{first.description}' ({first.line_id})",
                     formula=f"{_num(v.amount)}" + (f" + GST {_num(v.gst)}" if v.gst else ""),
                     rule_ref="expenses_actually_incurred", line_ids=(v.line_id,))
    payable_lines = [v for v in payable_lines if v.line_id not in duplicates]

    # 5c. bills dated outside the pre/post-hospitalisation days ----------------------
    outside = set()
    if claim.admission is not None:
        first_day = claim.admission - timedelta(days=rules.pre_hospitalisation_days)
        discharge = claim.discharge or claim.admission
        last_day = discharge + timedelta(days=rules.post_hospitalisation_days)
        for v in payable_lines:
            day = raw[v.line_id].date
            if day is None or first_day <= day <= last_day:
                continue
            if day < first_day:
                why = (f"{(claim.admission - day).days} days before admission; pre-hospitalisation cover is "
                       f"{rules.pre_hospitalisation_days} days")
                ref = "pre_hospitalisation"
            else:
                why = (f"{(day - discharge).days} days after discharge; post-hospitalisation cover is "
                       f"{rules.post_hospitalisation_days} days")
                ref = "post_hospitalisation"
            outside.add(v.line_id)
            b.deduct(f"D-WINDOW-{v.line_id}", DeductionKind.OUTSIDE_COVER_WINDOW, v.amount + v.gst,
                     f"Outside the cover window: '{v.description}' dated {day.isoformat()}, {why}",
                     formula=f"{_num(v.amount)}" + (f" + GST {_num(v.gst)}" if v.gst else ""),
                     rule_ref=ref, line_ids=(v.line_id,))
    payable_lines = [v for v in payable_lines if v.line_id not in outside]

    # 5d. road ambulance up to its limit per hospitalisation --------------------------
    ambulance = [v for v in payable_lines if v.category == Category.AMBULANCE]
    if ambulance:
        charged = sum((v.amount + v.gst for v in ambulance), ZERO)
        b.fact("F-AMBULANCE-LIMIT", "limit", f"Road ambulance limit: {_inr(rules.ambulance_max_inr)} per hospitalisation",
               rules.ambulance_max_inr, rule_ref="ambulance_limit", line_ids=_line_ids(ambulance))
        b.deduct("D-AMBULANCE", DeductionKind.AMBULANCE_LIMIT, charged - rules.ambulance_max_inr,
                 f"Road ambulance above the limit ({_inr(rules.ambulance_max_inr)} per hospitalisation)",
                 formula=f"{_num(charged)} - {_num(rules.ambulance_max_inr)}",
                 rule_ref="ambulance_limit", line_ids=_line_ids(ambulance))

    # 6. room-rent cap --------------------------------------------------------------
    room_cap = calc.room_cap_per_day(rules, si)
    b.fact("F-ROOM-CAP", "limit", f"Room rent limit: {_inr(room_cap)} a day", room_cap,
           formula=f"lower of {rules.room_pct_of_si}% of {_num(si)} and {_num(rules.room_max_inr)}",
           rule_ref="room_rent_cap", sum_insured=si)
    eligible_room = ZERO
    actual_room = ZERO
    over_cap_lines: list[str] = []
    for v in payable_lines:
        if v.category != Category.ROOM:
            continue
        line = raw[v.line_id]
        days, rate = D(line.qty), D(line.unit_rate)
        actual_room += rate * days
        eligible_room += min(rate, room_cap) * days
        excess = calc.excess_over_cap(rate, days, room_cap)
        if excess > 0:
            over_cap_lines.append(v.line_id)
            b.deduct(f"D-ROOM-{v.line_id}", DeductionKind.ROOM_RENT_EXCESS, excess,
                     f"Room rent above the limit ({_inr(rate - room_cap)} a day for {_num(days)} days)",
                     formula=f"{_num(days)} x ({_num(rate)} - {_num(room_cap)})",
                     rule_ref="room_rent_cap", line_ids=(v.line_id,))
            if line.gst_pct:
                b.deduct(f"D-ROOMGST-{v.line_id}", DeductionKind.ROOM_GST_EXCESS,
                         calc.gst_on(excess, line.gst_pct),
                         "GST on room rent above the limit",
                         formula=f"{line.gst_pct}% of {_num(excess)}",
                         rule_ref="gst_follows_charge", line_ids=(v.line_id,))

    # 7. ICU cap --------------------------------------------------------------------
    icu_lines = [v for v in payable_lines if v.category == Category.ICU]
    if icu_lines:
        icu_cap = calc.icu_cap_per_day(rules, si)
        b.fact("F-ICU-CAP", "limit", f"ICU limit: {_inr(icu_cap)} a day", icu_cap,
               formula=f"lower of {rules.icu_pct_of_si}% of {_num(si)} and {_num(rules.icu_max_inr)}",
               rule_ref="icu_cap", sum_insured=si)
        for v in icu_lines:
            line = raw[v.line_id]
            days, rate = D(line.qty), D(line.unit_rate)
            excess = calc.excess_over_cap(rate, days, icu_cap)
            if excess > 0:
                b.deduct(f"D-ICU-{v.line_id}", DeductionKind.ICU_EXCESS, excess,
                         f"ICU charges above the limit ({_inr(rate - icu_cap)} a day for {_num(days)} days)",
                         formula=f"{_num(days)} x ({_num(rate)} - {_num(icu_cap)})",
                         rule_ref="icu_cap", line_ids=(v.line_id,))
                if line.gst_pct:
                    b.deduct(f"D-ICUGST-{v.line_id}", DeductionKind.ICU_GST_EXCESS,
                             calc.gst_on(excess, line.gst_pct), "GST on ICU charges above the limit",
                             formula=f"{line.gst_pct}% of {_num(excess)}",
                             rule_ref="gst_follows_charge", line_ids=(v.line_id,))

    # 8. proportionate deduction ----------------------------------------------------
    if over_cap_lines:
        linked = [v for v in payable_lines if v.room_linked is True]
        unknown = [v for v in payable_lines if v.room_linked is None]
        excluded = [v for v in payable_lines if v.room_linked is False and v.category != Category.ROOM]
        linked_total = sum((v.amount + v.gst for v in linked), ZERO)
        excluded_total = sum((v.amount + v.gst for v in excluded), ZERO)
        b.fact("F-PROP-RATIO", "ratio",
               f"Eligible room rent {_inr(eligible_room)} of {_inr(actual_room)} charged",
               formula=f"{_num(eligible_room)} / {_num(actual_room)}",
               rule_ref="proportionate_deduction", line_ids=tuple(over_cap_lines),
               eligible_room=eligible_room, actual_room=actual_room)
        b.fact("F-PROP-LINKED", "base",
               f"Associated expenses the cut may apply to: {_inr(linked_total)}", linked_total,
               formula=" + ".join(_num(v.amount + v.gst) for v in linked) or "0",
               rule_ref="proportionate_deduction", line_ids=tuple(v.line_id for v in linked))
        b.fact("F-PROP-EXCLUDED", "base",
               f"Expenses the cut may not apply to (IRDAI 2020 norms): {_inr(excluded_total)}", excluded_total,
               formula=" + ".join(_num(v.amount + v.gst) for v in excluded) or "0",
               rule_ref="proportionate_deduction", line_ids=tuple(v.line_id for v in excluded),
               categories=sorted({v.category.value for v in excluded}))
        if unknown:
            names = ", ".join(f"'{v.description}'" for v in unknown)
            b.ask("Q-ROOM-PRICING",
                  f"Does the hospital charge different prices for {names} depending on the room type?",
                  "The proportionate deduction may only reduce charges the hospital prices by room category.",
                  tuple(v.line_id for v in unknown))
        else:
            b.deduct("D-PROPORTIONATE", DeductionKind.PROPORTIONATE,
                     calc.proportionate_deduction(linked_total, eligible_room, actual_room),
                     f"Proportionate deduction on associated expenses ({_num(eligible_room)} / {_num(actual_room)})",
                     formula=f"{_num(linked_total)} x ({_num(actual_room)} - {_num(eligible_room)}) / {_num(actual_room)}",
                     rule_ref="proportionate_deduction", line_ids=tuple(v.line_id for v in linked))

    # 9. cataract sub-limit ---------------------------------------------------------
    if calc.is_cataract(claim.diagnosis, claim.procedure, *(line.description for line in claim.lines)):
        _cataract(claim, policy, rules, history, b, claimed, si)

    return _finish(claim, b, lines, claimed, rules, policy, history)


def _cataract(claim: Claim, policy: Policy, rules: PolicyRules, history: list[PastClaim],
              b: _Builder, claimed: Decimal, si: Decimal) -> None:
    per_eye = calc.cataract_limit_per_eye(rules, si)
    b.fact("F-CATARACT-LIMIT", "limit", f"Cataract limit: {_inr(per_eye)} per eye per policy period", per_eye,
           formula=f"lower of {rules.cataract_pct_of_si}% of {_num(si)} and {_num(rules.cataract_max_inr)}",
           rule_ref="cataract_limit", sum_insured=si)
    eyes = calc.eyes_treated(claim.diagnosis, claim.procedure, *(line.description for line in claim.lines))
    so_far = claimed - b.deducted()
    if eyes is None:
        any_earlier = any(calc.is_cataract(c.diagnosis, c.procedure)
                          for c in calc.claims_in_period(policy, history, claim.claim_id))
        if so_far <= per_eye and not any_earlier:
            return  # under a single eye's limit with nothing used: the eye doesn't change the result
        b.ask("Q-EYE", "Was the cataract surgery on the right eye, the left eye, or both?",
              "The cataract limit applies per eye per policy period.")
        return
    remaining = ZERO
    parts = []
    for eye in sorted(eyes):
        used = calc.cataract_used_this_period(policy, history, eye, claim.claim_id)
        left = max(ZERO, per_eye - used)
        remaining += left
        parts.append(f"{eye}: {_num(per_eye)} - {_num(used)} used = {_num(left)}")
    b.fact("F-CATARACT-REMAINING", "limit",
           f"Cataract limit left this policy period: {_inr(remaining)}", remaining,
           formula="; ".join(parts), rule_ref="cataract_limit", eyes=sorted(eyes))
    if so_far > remaining:
        b.deduct("D-CATARACT", DeductionKind.CATARACT_LIMIT, so_far - remaining,
                 f"Cataract claim above the limit left ({_inr(remaining)})",
                 formula=f"{_num(so_far)} - {_num(remaining)}", rule_ref="cataract_limit")


def _finish(claim: Claim, b: _Builder, lines: list[LineView], claimed: Decimal, rules: PolicyRules,
            policy: Policy, history: list[PastClaim], not_admissible: bool = False) -> SettlementResult:
    """Steps 10-12, and the status."""
    if not_admissible:
        b.fact("F-PAYABLE", "payable", "Amount payable: ₹0", ZERO, formula="claim not admissible")
        return SettlementResult(claim.claim_id, Status.NOT_ADMISSIBLE, claimed, b.deductions,
                                ZERO, ZERO, ZERO, b.facts, b.questions, lines, b.warnings)
    if b.questions:
        return SettlementResult(claim.claim_id, Status.NEEDS_INFORMATION, claimed, b.deductions,
                                None, None, None, b.facts, b.questions, lines, b.warnings)

    admissible = round_paise(claimed - b.deducted())
    b.fact("F-ADMISSIBLE", "admissible", f"Admissible amount: {_inr(admissible)}", admissible,
           formula=f"claimed {_num(claimed)} - deductions {_num(b.deducted())}")
    co = calc.copay(admissible, rules.copay_pct)
    b.fact("F-COPAY", "copay", f"Co-pay {rules.copay_pct}%: {_inr(co)}", co,
           formula=f"{rules.copay_pct}% of {_num(admissible)}", rule_ref="copay")
    payable = admissible - co

    remaining_si = calc.remaining_sum_insured(policy, history, claim.claim_id)
    b.fact("F-SI-REMAINING", "limit", f"Sum insured left this policy period: {_inr(remaining_si)}",
           remaining_si, formula=f"{_num(policy.sum_insured)} - earlier claims this period",
           rule_ref="sum_insured")
    formula = f"admissible {_num(admissible)} - co-pay {_num(co)}"
    if payable > remaining_si:
        b.deduct("D-SUM-INSURED", DeductionKind.SUM_INSURED_EXHAUSTED, payable - remaining_si,
                 f"Above the sum insured left this policy period ({_inr(remaining_si)})",
                 formula=f"{_num(payable)} - {_num(remaining_si)}", rule_ref="sum_insured")
        payable = remaining_si
        formula += f", capped at sum insured left {_num(remaining_si)}"
    payable = round_paise(payable)
    b.fact("F-PAYABLE", "payable", f"Amount payable: {_inr(payable)}", payable, formula=formula)
    return SettlementResult(claim.claim_id, Status.COMPUTED, claimed, b.deductions,
                            admissible, co, payable, b.facts, b.questions, lines, b.warnings)
