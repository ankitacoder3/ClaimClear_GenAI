"""Matcher: work out how the insurer got each figure, and whether the wording allows it.

For every row of the insurer's letter the matcher:

  1. classifies the row (room rent, proportionate deduction, co-pay, ...);
  2. takes the policy-correct figure for that kind of row from the engine;
  3. runs the hypotheses for that kind and keeps those within ₹1 of the insurer's figure;
  4. gives a verdict:

     * ``matches_policy``: the insurer's figure is what the wording requires.
     * ``does_not_match_policy``: a documented wrong method reproduces it. One match
       identifies the method. Several matches give the same verdict plus one
       question that tells them apart.
     * ``method_matches`` (co-pay only): the right method, on a base that carries
       another row's error. Not disputable on its own; the error is counted in
       that other row.
     * ``not_verifiable``: nothing tested reproduces it. The next step is to ask
       the insurer for an itemised breakdown and the clause. If only some
       hypotheses were tested (``exhaustive=False``), the auditor should replan
       and test the rest first.

``audit_letter`` does this for every row, adds the co-pay and any rejection as
rows, and computes the rupee summary: what the wording requires, what was paid,
how much may be disputable and how much can't be checked (both after co-pay).

The model proposes which hypotheses to test (``hypothesis_ids``); this code
computes and matches; the policyholder decides whether to dispute.
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Iterable, Optional

from .engine import _inr, compute_settlement
from .hypotheses import (
    HYPOTHESES,
    NAMED_LINE_KINDS,
    ROW_DEDUCTIONS,
    ROW_RULE_REF,
    CaseContext,
    Hypothesis,
    list_hypotheses,
    named_lines,
    row_policy_amount,
)
from .models import (
    Category,
    Claim,
    HypothesisMatch,
    LetterAudit,
    LetterRow,
    PastClaim,
    Policy,
    PolicyRules,
    Question,
    RowAudit,
    RowKind,
    SettlementLetter,
    Status,
    Verdict,
)
from .money import D, ZERO, round_paise

TOLERANCE = D(1)  # ₹1, for rounding at a different step

# First match wins. GST before room/ICU; proportionate before room ("room category ... proportion").
ROW_PATTERNS: list[tuple[RowKind, re.Pattern[str]]] = [
    (RowKind.COPAY, re.compile(r"\b(co-?pay\w*|co-?payment)\b", re.I)),
    (RowKind.ALREADY_PAID, re.compile(r"\balready (been )?(settled|paid)\b|\bpaid twice\b|\bduplicate claim\b|"
                                      r"\bcannot be paid (again|twice)\b", re.I)),
    (RowKind.UNITEMISED, re.compile(r"\bnot supported by (the )?itemi[sz]ed\b|\bnot itemi[sz]ed\b|\bunitemi[sz]ed\b|"
                                    r"\bno itemi[sz]ed (break-?up|details)\b", re.I)),
    (RowKind.DUPLICATE, re.compile(r"\b(duplicat\w*|billed twice|charged twice|double[- ]?(billed|charged|billing))\b", re.I)),
    (RowKind.COVER_WINDOW, re.compile(r"\b(pre|post)[- ]?hospitali[sz]ation\b", re.I)),
    (RowKind.AMBULANCE, re.compile(r"\bambulance\b", re.I)),
    # Annexure A: "List II (part of room charges)" is an item list, not a room-rent row.
    (RowKind.NON_PAYABLE, re.compile(r"\b(list\s+(i{1,3}|iv|v)|annexure|subsumed|part of (the )?(room|procedure) "
                                     r"charges|part of (the )?costs? of treatment)\b", re.I)),
    (RowKind.POLICY_PERIOD, re.compile(r"\b(outside|beyond|not within|before|after)\b.{0,40}\bpolicy period\b|"
                                       r"\bpolicy (had )?(lapsed|expired)\b|\bnot in force\b", re.I)),
    (RowKind.ROOM_GST, re.compile(r"\bgst\b.*\b(room|ward)\b|\b(room|ward)\b.*\bgst\b", re.I)),
    (RowKind.ICU_GST, re.compile(r"\bgst\b.*\bicu\b|\bicu\b.*\bgst\b", re.I)),
    (RowKind.PROPORTIONATE, re.compile(r"\b(proportion\w*|associated (medical )?expenses|pro-?rata)\b", re.I)),
    (RowKind.ROOM_AND_ICU, re.compile(r"\b(room|ward)\b.{0,15}\b(icu|iccu)\b|\b(icu|iccu)\b.{0,15}\b(room|ward)\b",
                                      re.I)),
    (RowKind.ICU, re.compile(r"\b(icu|intensive care)\b", re.I)),
    (RowKind.ROOM_RENT, re.compile(r"\b(room rent|room charges?|room category|ward charges?|accommodation)\b", re.I)),
    (RowKind.NON_PAYABLE, re.compile(r"\b(non-?payable|not payable|inadmissible items?|consumables?)\b", re.I)),
    (RowKind.CATARACT, re.compile(r"\b(cataract)\b", re.I)),
    (RowKind.WAITING_PERIOD, re.compile(r"\b(waiting period|pre-?existing|not completed)\b", re.I)),
    (RowKind.SUM_INSURED, re.compile(r"\b(sum insured|exhausted|balance sum)\b", re.I)),
]


def classify_row(particulars: str, reason: str = "") -> RowKind:
    """Kind of a letter row from its wording. ``UNSPECIFIED`` when nothing matches."""
    for text in (particulars, reason):
        for kind, pattern in ROW_PATTERNS:
            if pattern.search(text or ""):
                return kind
    return RowKind.UNSPECIFIED


def _within(a: Decimal, b: Decimal) -> bool:
    return abs(D(a) - D(b)) <= TOLERANCE


_ORDER = {hid: i for i, hid in enumerate(HYPOTHESES)}


def _merge_equivalent(matches: list[HypothesisMatch]) -> list[HypothesisMatch]:
    """Collapse hypotheses that did the same calculation on this bill.

    "Cut every non-room line" and "cut every non-room line incl. ICU" are the
    same calculation on a bill with no ICU line: same lines, same amount. Keep
    the first one registered (the more general wording) and drop the rest, so a
    real tie is only reported when the methods touch different lines. Matches
    with no line IDs (co-pay, waiting period, cataract) are never merged.
    """
    kept: dict[tuple, HypothesisMatch] = {}
    out = []
    for m in sorted(matches, key=lambda x: _ORDER.get(x.hypothesis_id, 10**6)):
        if not m.line_ids:
            out.append(m)
            continue
        key = (frozenset(m.line_ids), m.amount)
        if key not in kept:
            kept[key] = m
            out.append(m)
    return out


def _applicable(kind: RowKind, other_row_kinds: Iterable[RowKind]) -> list[Hypothesis]:
    """Hypotheses to test for a row of ``kind``.

    An unspecified row ("Other deductions") is tested against every hypothesis
    except co-pay and whole-claim rejections, and except kinds the letter already
    shows on rows of their own, so the same rupees aren't explained twice.
    """
    if kind != RowKind.UNSPECIFIED:
        return list_hypotheses(kind)
    skip = set(other_row_kinds) | {RowKind.COPAY, RowKind.WAITING_PERIOD, RowKind.UNSPECIFIED}
    return [h for h in list_hypotheses() if h.kind not in skip]


def reproduce_row(
    ctx: CaseContext,
    row: LetterRow,
    hypothesis_ids: Optional[Iterable[str]] = None,
    other_row_kinds: Iterable[RowKind] = (),
) -> RowAudit:
    """Verdict on one letter row.

    ``hypothesis_ids`` limits the test to the hypotheses the auditor picked; the
    correct method for the row's kind is always tested too. Unknown IDs are ignored.
    """
    kind, kind_source = (row.kind, "input") if row.kind else (classify_row(row.particulars, row.reason), "keyword")
    amount = D(row.amount)
    applicable = _applicable(kind, other_row_kinds)
    if hypothesis_ids is not None:
        wanted = set(hypothesis_ids)
        tested_hs = [h for h in applicable if h.hypothesis_id in wanted or (h.correct and h.kind == kind)]
    else:
        tested_hs = applicable
    tested = [h.hypothesis_id for h in tested_hs]
    exhaustive = len(tested_hs) == len(applicable)
    rule_ref = ROW_RULE_REF.get(kind, "")
    fact_ids = [d.fact_id for d in ctx.result.deductions if d.kind in ROW_DEDUCTIONS[kind]]
    if kind == RowKind.COPAY and ctx.result.fact("F-COPAY"):
        fact_ids = ["F-COPAY"]

    base = dict(row_id=row.row_id, particulars=row.particulars, kind=kind, kind_source=kind_source,
                insurer_amount=amount, tested=tested, exhaustive=exhaustive, rule_ref=rule_ref,
                policy_fact_ids=fact_ids)

    # The engine needs an answer first: no verdict on any row until it has one.
    if ctx.result.status == Status.NEEDS_INFORMATION:
        return RowAudit(**base, policy_amount=None, difference=None, verdict=Verdict.NOT_VERIFIABLE, method=None,
                        explanation="The policy-correct figure can't be worked out until the questions are answered.",
                        matches=[], questions=list(ctx.result.questions))

    row_ctx = replace(ctx, row=row)
    total_policy = ctx.policy_amount(kind)
    policy_amount = row_policy_amount(row_ctx, kind)
    matches: list[HypothesisMatch] = []
    for h in tested_hs:
        for c in h.run(row_ctx):
            if c.amount > 0 and _within(c.amount, amount):
                matches.append(HypothesisMatch(h.hypothesis_id, h.correct, h.title, c.amount, c.detail, c.line_ids))

    def audit(verdict: Verdict, method: Optional[str], explanation: str, policy: Decimal,
              questions: Optional[list[Question]] = None) -> RowAudit:
        return RowAudit(**base, policy_amount=round_paise(policy), difference=round_paise(amount - policy),
                        verdict=verdict, method=method, explanation=explanation, matches=matches,
                        questions=questions or [])

    # 1. The figure is what the wording requires (for the lines the row names, or for every line of its kind).
    if kind in NAMED_LINE_KINDS and _within(amount, total_policy) and amount > 0:
        policy_amount = total_policy
    if _within(amount, policy_amount) and (amount > 0 or policy_amount == 0):
        method = f"{kind.value}_policy" if kind != RowKind.UNSPECIFIED else None
        if policy_amount != total_policy and f"{kind.value}_named_items" in HYPOTHESES:
            method = f"{kind.value}_named_items"   # the policy figure for the items this row names
        return audit(Verdict.MATCHES_POLICY, method,
                     f"{_inr(amount)} is what the policy requires for this row ({_inr(policy_amount)}).",
                     policy_amount)

    # The row names some of the items of its kind (a letter that splits them over rows), and the
    # policy-correct figure for exactly those items is the insurer's figure.
    if kind != RowKind.UNSPECIFIED:
        part = [m for m in matches if m.correct and m.hypothesis_id != f"{kind.value}_policy"]
        if part:
            m = part[0]
            return audit(Verdict.MATCHES_POLICY, m.hypothesis_id,
                         f"{_inr(amount)} is what the policy requires for the items this row names ({m.detail}).",
                         m.amount)

    # An unlabelled row that equals a policy-correct deduction of another kind.
    if kind == RowKind.UNSPECIFIED:
        correct = [m for m in matches if m.correct]
        if correct:
            m = correct[0]
            return audit(Verdict.MATCHES_POLICY, m.hypothesis_id,
                         f"The letter doesn't say what {_inr(amount)} is for, but it equals the policy's "
                         f"'{m.title}' ({m.detail}).", m.amount)

    # 2. Co-pay: right method, insurer's base.
    method_only = [m for m in matches if HYPOTHESES[m.hypothesis_id].method_only]
    if method_only:
        m = method_only[0]
        return audit(Verdict.METHOD_MATCHES, m.hypothesis_id,
                     f"The co-pay is worked out the right way ({m.detail}), but on the insurer's admissible amount. "
                     f"The policy-correct co-pay is {_inr(policy_amount)}; the difference comes from the insurer's "
                     "other deductions and is counted there.", policy_amount)

    # 3. A documented wrong method reproduces it.
    wrong = _merge_equivalent([m for m in matches if not m.correct])
    methods = list(dict.fromkeys(m.hypothesis_id for m in wrong))
    if len(methods) == 1:
        m = wrong[0]
        return audit(Verdict.DOES_NOT_MATCH_POLICY, m.hypothesis_id,
                     f"The policy requires {_inr(policy_amount)}. The insurer's {_inr(amount)} is reproduced by: "
                     f"{m.title} ({m.detail}). Difference {_inr(amount - policy_amount)}.", policy_amount)
    if len(methods) > 1:
        titles = "; ".join(HYPOTHESES[i].title for i in methods)
        asked = next((HYPOTHESES[i].question for i in methods if HYPOTHESES[i].question), "")
        q = Question(f"Q-TIE-{row.row_id}",
                     asked or f"Two calculations give {_inr(amount)}: {titles}. Can the insurer say which it used?",
                     f"Several methods reproduce {_inr(amount)}: {titles}.", ())
        return audit(Verdict.DOES_NOT_MATCH_POLICY, None,
                     f"The policy requires {_inr(policy_amount)}. The insurer's {_inr(amount)} can be reproduced "
                     f"{len(methods)} ways: {titles}. Difference {_inr(amount - policy_amount)}.",
                     policy_amount, [q])

    # 4. Nothing reproduces it, but the engine has the policy figure and the insurer took more. Not
    #    knowing how the insurer got its number doesn't make the deduction right: the row doesn't match
    #    the policy, and the insurer is asked for its working. (A line the engine couldn't recognise is
    #    the exception: whether it is on the non-payable list is asked instead.) "Already settled" is
    #    never called out: the engine sees only the claim history it is given, so finding no earlier
    #    claim doesn't show there wasn't one.
    if (exhaustive and kind not in (RowKind.UNSPECIFIED, RowKind.ALREADY_PAID)
            and amount - policy_amount > TOLERANCE):
        if kind in (RowKind.SUM_INSURED, RowKind.CATARACT) and not ctx.history:
            # The figure depends on earlier claims this policy year, and the engine was given none.
            q = Question(f"Q-HISTORY-{row.row_id}",
                         "Were there earlier claims on this policy in the same policy year? The insurer's "
                         f"{_inr(amount)} may count them.",
                         "The sum insured left and the cataract limit per eye depend on earlier claims.", ())
            return audit(Verdict.NOT_VERIFIABLE, None,
                         f"The policy requires {_inr(policy_amount)} if there were no earlier claims this policy "
                         f"year; the insurer's {_inr(amount)} may count claims the engine wasn't given.",
                         policy_amount, [q])
        named = named_lines(row_ctx, list(ctx.result.lines)) if kind in NAMED_LINE_KINDS else []
        unknown = [v for v in named if v.category == Category.UNKNOWN and not v.non_payable]
        named_total = sum((v.amount + v.gst for v in named), ZERO)
        whole_line = any(_within(v.amount + v.gst, amount) for v in named)
        if kind == RowKind.NON_PAYABLE and named and not unknown and not whole_line and amount < named_total - TOLERANCE:
            # Part of a line that groups many items ("Pharmacy items not payable as per annexure"): which
            # items were cut can't be seen on the bill, so the insurer's item list is needed first.
            names = ", ".join(f"'{v.description}'" for v in named)
            q = Question(f"Q-ITEMS-{row.row_id}",
                         f"Ask the insurer which items in {names} make up {_inr(amount)}, and where the policy "
                         "lists them.",
                         f"{_inr(amount)} is part of {_inr(named_total)}; the bill doesn't show the items.", ())
            return audit(Verdict.NOT_VERIFIABLE, None,
                         f"{_inr(amount)} is part of {names} ({_inr(named_total)}), and the bill doesn't show which "
                         "items it covers, so it can't be checked yet.", policy_amount, [q])
        if not unknown:
            q = Question(f"Q-BREAKDOWN-{row.row_id}",
                         f"Ask the insurer how it worked out '{row.particulars}' ({_inr(amount)}) and which policy "
                         "clause it relies on.",
                         f"The policy allows {_inr(policy_amount)} for this row; no known calculation gives "
                         f"{_inr(amount)}.", ())
            return audit(Verdict.DOES_NOT_MATCH_POLICY, None,
                         f"The policy requires {_inr(policy_amount)} for this row. The insurer deducted "
                         f"{_inr(amount)}, {_inr(amount - policy_amount)} more, and no known calculation gives its "
                         "figure.", policy_amount, [q])
        names = ", ".join(f"'{v.description}'" for v in unknown)
        q = Question(f"Q-ITEM-{row.row_id}",
                     f"Is {names} on the policy's list of non-payable items (Annexure A)?",
                     "The engine doesn't recognise the item, so it can't say whether the deduction is right.",
                     tuple(v.line_id for v in unknown))
        return audit(Verdict.NOT_VERIFIABLE, None,
                     f"The engine doesn't recognise {names}, so it can't tell whether {_inr(amount)} is right.",
                     policy_amount, [q])

    # 5. Nothing reproduces it, and it is not more than the policy allows.
    if not exhaustive:
        untested = [h.hypothesis_id for h in applicable if h.hypothesis_id not in tested]
        return audit(Verdict.NOT_VERIFIABLE, None,
                     f"None of the {len(tested)} calculations tested gives {_inr(amount)}. "
                     f"{len(untested)} more can be tested: {', '.join(untested)}.", policy_amount)
    q = Question(f"Q-BREAKDOWN-{row.row_id}",
                 f"Ask the insurer for an itemised breakdown of '{row.particulars}' ({_inr(amount)}) "
                 "and the policy clause it relies on.",
                 f"No known calculation gives {_inr(amount)}.", ())
    return audit(Verdict.NOT_VERIFIABLE, None,
                 f"No known calculation gives {_inr(amount)}"
                 + (f"; the policy requires {_inr(policy_amount)} for this row." if kind != RowKind.UNSPECIFIED
                    else ", and the letter gives no item or clause for it."),
                 policy_amount, [q])


def letter_rows(letter: SettlementLetter) -> list[LetterRow]:
    """The letter's rows plus the co-pay and, for a rejection, the whole claim as rows."""
    rows = list(letter.rows)
    if letter.copay_amount is not None and letter.letter_type != "rejection":
        rows.append(LetterRow("COPAY", "Co-pay", D(letter.copay_amount), kind=RowKind.COPAY))
    if letter.letter_type == "rejection":
        kind = classify_row(letter.rejection_reason)
        if kind not in (RowKind.WAITING_PERIOD, RowKind.POLICY_PERIOD, RowKind.ALREADY_PAID):
            kind = RowKind.UNSPECIFIED
        rows.append(LetterRow("REJECTION", letter.rejection_reason or "Claim rejected", D(letter.claimed_amount),
                              kind=kind))
    return rows


def _prepare(letter: SettlementLetter, claim: Claim, policy: Policy, rules: PolicyRules,
             history: Iterable[PastClaim]) -> tuple[CaseContext, list[LetterRow], list[RowKind]]:
    history = list(history)
    result = compute_settlement(claim, policy, rules, history)
    ctx = CaseContext(claim, policy, rules, history, result, letter)
    rows = letter_rows(letter)
    kinds = [r.kind or classify_row(r.particulars, r.reason) for r in rows]
    return ctx, rows, kinds


def _others(kinds: list[RowKind], i: int) -> list[RowKind]:
    """Kinds shown on the letter's other rows (for unspecified-row matching)."""
    return [k for j, k in enumerate(kinds) if j != i and k != RowKind.UNSPECIFIED]


def reproduce_letter_row(
    letter: SettlementLetter,
    claim: Claim,
    policy: Policy,
    rules: PolicyRules,
    history: Iterable[PastClaim] = (),
    row_id: str = "",
    hypothesis_ids: Optional[Iterable[str]] = None,
) -> RowAudit:
    """Verdict on one row of ``letter``, in the context of the whole letter.

    ``row_id`` is a letter row's ID, or ``COPAY`` / ``REJECTION`` for the rows
    ``letter_rows`` adds. Raises ``KeyError`` if there is no such row.
    """
    ctx, rows, kinds = _prepare(letter, claim, policy, rules, history)
    for i, row in enumerate(rows):
        if row.row_id == row_id:
            return reproduce_row(ctx, row, hypothesis_ids, _others(kinds, i))
    raise KeyError(row_id)


def audit_letter(
    letter: SettlementLetter,
    claim: Claim,
    policy: Policy,
    rules: PolicyRules,
    history: Iterable[PastClaim] = (),
    hypothesis_ids: Optional[Iterable[str]] = None,
) -> LetterAudit:
    """Verdict on every row of ``letter``, and the rupee summary."""
    ctx, rows, explicit = _prepare(letter, claim, policy, rules, history)
    result = ctx.result
    audits = [reproduce_row(ctx, row, hypothesis_ids, _others(explicit, i)) for i, row in enumerate(rows)]

    warnings = list(result.warnings)
    paid = D(letter.paid_amount)
    copay = D(letter.copay_amount or 0)
    if letter.letter_type == "rejection":
        arithmetic = round_paise(-paid)
    else:
        arithmetic = round_paise(D(letter.claimed_amount) - sum((D(r.amount) for r in letter.rows), ZERO) - copay - paid)
    if abs(arithmetic) > TOLERANCE:
        warnings.append(f"The letter does not add up: claimed less deductions and co-pay differs from the amount "
                        f"paid by {_inr(arithmetic)}.")
    if abs(D(letter.claimed_amount) - result.claimed_amount) > TOLERANCE:
        warnings.append(f"The letter's claimed amount {_inr(D(letter.claimed_amount))} differs from the bill's "
                        f"{_inr(result.claimed_amount)}.")

    present = set(explicit) | {a.kind for a in audits}
    matched_ids = {a.method for a in audits if a.method}
    not_on_letter = []
    for kind, kinds in ROW_DEDUCTIONS.items():
        if kind in present or f"{kind.value}_policy" in matched_ids:
            continue
        for d in result.deductions:
            if d.kind in kinds:
                not_on_letter.append(f"{d.description}: {_inr(d.amount)}")

    questions: list[Question] = []
    for a in audits:
        for q in a.questions:
            if all(q.question_id != x.question_id for x in questions):
                questions.append(q)

    if result.status == Status.NEEDS_INFORMATION:
        return LetterAudit(letter.letter_id, result, audits, None, paid, None, None, None, None,
                           arithmetic, not_on_letter, questions, warnings)

    payable = result.payable_amount
    gap = round_paise(payable - paid)
    keep = (D(100) - rules.copay_pct) / D(100)
    unverified_raw = sum((max(ZERO, a.difference) for a in audits
                          if a.verdict == Verdict.NOT_VERIFIABLE and a.difference is not None), ZERO)
    unverified = round_paise(min(max(ZERO, gap), unverified_raw * keep))
    disputable = round_paise(max(ZERO, gap - unverified))
    overpaid = round_paise(max(ZERO, -gap))
    return LetterAudit(letter.letter_id, result, audits, payable, paid, gap, unverified, disputable, overpaid,
                       arithmetic, not_on_letter, questions, warnings)
