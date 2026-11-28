"""The checked document reader: ``extraction.llm_extractor`` with four fixes for what the dev cases showed (an add-on:
``extraction.py`` is unchanged and its prompt, normaliser, arithmetic checks and second ask are reused as they are).

Why (development cases, 26 Nov 2026; "Why the Dev Cases Passed, Then Failed"): given a correct reading the engine got
every verdict right, and every product-path failure came from the reading. Four reading errors were found, and this
reader removes each in plain code:

1. **The co-pay read twice.** The letter prints its co-payment among the deductions; the model put it in
   ``copay_amount`` and again as a deduction row, so the engine checked it twice and ``letter_issues`` never added up.
   ``fold_copay`` removes the repeat (or moves a lone co-pay row into ``copay_amount``) and numbers the rows again the
   way the letter's own rows and the answer files count them (R1, R2, ... without the co-pay).
2. **The insurer's reasons copied onto the bill.** The bill is read beside the letter, so the model marked bill lines
   "not payable" because the insurer said so, and the engine then agreed with the insurer (gen-dev-6ad373: a payable
   blood product, Rs 9,595 short). ``engine_decides`` clears the model's per-line ``non_payable`` and ``category``
   and the letter rows' ``kind``: the engine works them out from the printed words, as it does for every correct
   reading (all 42 dev cases give the same results with these fields cleared).
3. **Lines dropped from a second bill.** When the bill lines still don't add up to the printed total after the second
   ask, each bill file is read on its own and the lines are joined (gen-dev-3ce156: the three lines of
   ``other_bills.pdf`` were missed in one run).
4. **Readings that change from run to run.** The bill is read ``CLAIMCLEAR_READER_VOTES`` times at once (default 2)
   and the reading that adds up is kept; the bill and the letter are read at the same time, so this costs no waiting.

``make_extractor(llm)`` is what the apps call: this reader, or the original one with ``CLAIMCLEAR_READER=classic``
(for comparisons). ``checks`` keeps the original shape (``found`` / ``left`` per document) and adds what was done.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from decimal import Decimal
from typing import Any, Optional

from . import extraction as ex

log = logging.getLogger("claimclear.graph")

READER_ENV = "CLAIMCLEAR_READER"            # "classic": the original llm_extractor; anything else: this reader
VOTES_ENV = "CLAIMCLEAR_READER_VOTES"       # bill readings made at once (1-3, default 2)
DEFAULT_VOTES = 2
FILE_ROLES = ("bill", "other_bills")        # the files whose lines make up the claim
COPAY_TEXT = re.compile(r"\bco[-\s]?pay(ment)?\b", re.I)
ROW_ID = re.compile(r"^R(\d+)$")
ONE_FILE = ("\n\nThe documents above are ONE of the hospital's bills for this claim. List every line item printed on "
            "it, in order, exactly as printed, including a line that repeats an earlier one.")


def votes() -> int:
    try:
        return max(1, min(3, int(os.environ.get(VOTES_ENV, "") or DEFAULT_VOTES)))
    except ValueError:
        return DEFAULT_VOTES


# --------------------------------------------------------------------------- plain-code fixes on a reading


def is_copay_row(row: dict) -> bool:
    return row.get("kind") == "copay" or bool(COPAY_TEXT.search(str(row.get("particulars") or "")))


def _renumbered(rows: list[dict], before: list[dict]) -> list[dict]:
    """Rows numbered R1..Rn again, when the reading numbered every row R1..Rm in order (so the labels were counted,
    not printed out of order); otherwise the labels are kept as read."""
    ids = [ROW_ID.match(str(r.get("row_id") or "")) for r in before]
    if not all(ids) or [int(m.group(1)) for m in ids] != list(range(1, len(before) + 1)):
        return rows
    return [{**r, "row_id": f"R{i}"} for i, r in enumerate(rows, start=1)]


def fold_copay(letter: dict) -> dict:
    """The co-payment belongs in ``copay_amount`` only: the engine adds its own COPAY row.

    * ``copay_amount`` read and a co-pay row of the same amount (within Rs 1): the row is a repeat and is dropped.
    * no ``copay_amount`` and co-pay rows: their amounts move into ``copay_amount``.
    * anything else (a co-pay row of a different amount): left as read.
    """
    rows = list(letter.get("rows") or [])
    copay = [r for r in rows if is_copay_row(r)]
    if not copay or letter.get("letter_type") == "rejection":
        return letter
    have = ex._dec(letter.get("copay_amount"))
    out = dict(letter)
    if have:
        drop = [r for r in copay if (a := ex._dec(r.get("amount"))) is not None and abs(a - have) <= ex.TOLERANCE]
        if not drop:
            return letter
    else:
        amounts = [ex._dec(r.get("amount")) for r in copay]
        if any(a is None for a in amounts):
            return letter
        drop = copay
        out["copay_amount"] = str(sum(amounts, Decimal(0)))
    keep = [r for r in rows if not any(r is d for d in drop)]
    out["rows"] = _renumbered(keep, rows)
    return out


def engine_decides(claim: Optional[dict] = None, letter: Optional[dict] = None) -> tuple[Optional[dict], Optional[dict]]:
    """Clear the judgements the engine makes itself: each bill line's ``non_payable`` and ``category``, and each
    letter row's ``kind``. What is printed (descriptions, amounts, labels) is kept."""
    if claim is not None:
        claim = {**claim, "lines": [{k: v for k, v in line.items() if k not in ("non_payable", "category")}
                                    for line in claim.get("lines") or []]}
    if letter is not None:
        letter = {**letter, "rows": [{k: v for k, v in row.items() if k != "kind"} for row in letter.get("rows") or []]}
    return claim, letter


def _fingerprint(claim: dict) -> tuple:
    amounts = [ex._dec(x.get("amount")) for x in claim.get("lines") or []]
    total = sum((a for a in amounts if a is not None), Decimal(0))
    return len(amounts), str(total.quantize(Decimal("0.01")))


# --------------------------------------------------------------------------- the reads


async def _bill_votes(reader: Any, schema: dict, prompt: str, n: int) -> tuple[dict, list[str], list[str], dict]:
    """``n`` bill readings at once (each with ``extraction``'s second ask); keep the one that adds up best."""
    got = await asyncio.gather(*(ex._read(reader, schema, prompt, ex.bill_issues) for _ in range(n)),
                               return_exceptions=True)
    ok = [g for g in got if not isinstance(g, BaseException)]
    if not ok:
        raise got[0]
    best = min(ok, key=lambda g: (len(g[2]), -len(g[0].get("lines") or [])))
    info = {"votes": len(ok), "agreed": len({_fingerprint(g[0]) for g in ok}) == 1}
    return best[0], best[1], best[2], info


async def _per_file(reader: Any, schema: dict, claim: dict, documents: list[dict], pages: dict) -> Optional[dict]:
    """Each bill file read on its own, the lines joined in file order, the rest of the claim kept as read."""
    files = [d for d in documents if d.get("role") in FILE_ROLES and d["document_id"] in pages]
    if not files:
        return None
    parts = await asyncio.gather(*(ex._ask(reader, ex._prompt(ex._text([d], pages, FILE_ROLES)) + ONE_FILE)
                                   for d in files), return_exceptions=True)
    lines: list[dict] = []
    for part in parts:
        if isinstance(part, BaseException):
            log.info("per-file bill read failed (%s)", type(part).__name__)
            return None
        lines += ex.normalise(dict(part), schema).get("lines") or []
    return {**claim, "lines": lines} if lines else None


def checked_extractor(llm: Any):
    """An ``Extractor`` (same call and result as ``extraction.llm_extractor``) with the four fixes above."""
    from .chat import with_max_tokens
    llm = with_max_tokens(llm, ex.extraction_max_tokens())

    async def extract(toolkit: Any, case_id: str, documents: list[dict], pages: dict[str, dict]) -> dict:
        claim_schema, letter_schema = toolkit.schema("ClaimIn"), toolkit.schema("LetterIn")
        claim_reader = llm.with_structured_output(claim_schema)
        letter_reader = llm.with_structured_output(letter_schema)
        bill_prompt = ex._prompt(ex._text(documents, pages, ex.BILL_ROLES + ex.LETTER_ROLES))
        letter_prompt = ex._prompt(ex._text(documents, pages, ex.LETTER_ROLES))

        (claim, bill_found, bill_left, bill_info), (letter, letter_found, letter_left) = await asyncio.gather(
            _bill_votes(claim_reader, claim_schema, bill_prompt, votes()),
            ex._read(letter_reader, letter_schema, letter_prompt, lambda reading: ex.letter_issues(fold_copay(reading))))

        per_file = False
        if bill_left:
            joined = await _per_file(claim_reader, claim_schema, claim, documents, pages)
            if joined is not None and len(ex.bill_issues(joined)) < len(bill_left):
                claim, bill_left, per_file = joined, ex.bill_issues(joined), True

        folded = fold_copay(letter)
        claim, letter = engine_decides(claim, folded)
        return {"claim": claim, "letter": letter, "sources": {},
                "checks": {"bill": {"found": bill_found, "left": bill_left, **bill_info, "per_file": per_file},
                           "letter": {"found": letter_found, "left": letter_left,
                                      "copay_folded": folded is not letter}}}

    return extract


def make_extractor(llm: Any):
    """The reader the apps use: this one, or ``extraction.llm_extractor`` when ``CLAIMCLEAR_READER=classic``."""
    if llm is None:
        return None
    if (os.environ.get(READER_ENV) or "").strip().lower() == "classic":
        return ex.llm_extractor(llm)
    return checked_extractor(llm)
