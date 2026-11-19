"""Load cases from the standard dataset (``dev_data/dataset/``) into engine inputs.

The engine itself never reads files. This adapter turns the dataset's JSON into ``Claim``, ``Policy``,
``PastClaim`` and ``PolicyRules`` objects. In the full system the same objects come from the document
reader agent and the ``case-records`` MCP server.

Documents are found by their dataset ID (``GEN-02``, ``SET-01``): each synthetic case's answer file
(``<split>/answers/<case_id>.json``) holds its documents' extracted fields under ``source_answer``,
next to the answer key (expected verdicts and amounts). This module reads only the bill and the
letter as printed, plus the split's ``reference/``; tests read the answer key separately, and
nothing here passes it to the engine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .identifiers import canonical_policy_no, same_policy
from .models import BillLine, Claim, LetterRow, PastClaim, Policy, PolicyRules, SettlementLetter
from .money import D, to_date
from .rules import load_rules

ENV_VAR = "CLAIMCLEAR_DATASET_DIR"
SPLITS = ("dev", "heldout")


def default_dataset_dir() -> Path:
    """``$CLAIMCLEAR_DATASET_DIR``, else ``<repo>/dev_data/dataset``."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    # engine/ -> settlement_engine/ -> servers/ -> repo root
    return Path(__file__).resolve().parents[3] / "dev_data" / "dataset"


@dataclass(frozen=True)
class Case:
    """Everything the engine needs for one claim."""

    claim: Claim
    policy: Policy
    rules: PolicyRules
    history: tuple[PastClaim, ...]
    bill_doc_id: str


@lru_cache(maxsize=4)
def _manifest(dataset_dir: str) -> dict[str, dict]:
    """Dataset document ID -> its record (with ``split`` and ``case_id`` added), from every answer file."""
    docs: dict[str, dict] = {}
    for split in SPLITS:
        for path in sorted((Path(dataset_dir) / split / "answers").glob("*.json")):
            answer = json.loads(path.read_text(encoding="utf-8"))
            if answer.get("source") != "claimclear-synthetic":
                continue
            for doc_id, record in answer["source_answer"].items():
                docs[doc_id] = {**record, "split": split, "case_id": answer["case_id"]}
    return docs


def _json(dataset_dir: Path, split: str, name: str):
    with open(dataset_dir / split / "reference" / name, encoding="utf-8") as fh:
        return json.load(fh)


def _for_case(records: list[dict], case_id: str) -> list[dict]:
    """Records for this case: a record tagged with a ``case_id`` belongs to that case only."""
    return [r for r in records if r.get("case_id") in (None, "", case_id)]


def policy_from_dict(p: dict) -> Policy:
    return Policy(
        policy_no=p["policy_no"],
        sum_insured=D(p["sum_insured"]),
        period_start=to_date(p["period_start"]),
        period_end=to_date(p["period_end"]),
        first_inception=to_date(p["first_inception"]),
        holder=p.get("holder", ""),
        insurer=p.get("insurer", ""),
        product=p.get("product", ""),
    )


def past_claim_from_dict(c: dict) -> PastClaim:
    return PastClaim(
        claim_id=c["claim_id"],
        policy_no=c["policy_no"],
        admission=to_date(c["admission"]),
        status=c["status"],
        settled_amount=D(c["settled_amount"]),
        diagnosis=c.get("diagnosis", ""),
        procedure=c.get("procedure", ""),
    )


def claim_from_invoice(inv: dict, claim_id: str) -> Claim:
    """Build a ``Claim`` from one ``invoices[]`` entry of a bill's record.

    Only bill fields are used. ``non_payable`` comes from the bill extraction;
    category is left for the engine to work out from the description.
    """
    lines = tuple(
        BillLine(
            line_id=f"L{i:02d}",
            description=li["description"],
            amount=D(li["printed_amount"]),
            qty=D(li.get("qty") or 1),
            rate=D(li["rate"]) if li.get("rate") is not None else None,
            gst_pct=D(li.get("gst_pct") or 0),
            non_payable=True if li.get("non_payable") else None,   # a bill can only mark a line non-payable
            date=to_date(li["date"]) if li.get("date") else None,
        )
        for i, li in enumerate(inv["line_items"], start=1)
    )
    return Claim(
        claim_id=claim_id,
        policy_no=inv["policy_no"],
        admission=to_date(inv["admission"]) if inv.get("admission") else None,
        discharge=to_date(inv["discharge"]) if inv.get("discharge") else None,
        lines=lines,
        diagnosis=inv.get("diagnosis") or "",
        procedure=inv.get("procedure") or "",
        discount=D(inv.get("discount") or 0),
        printed_total=D(inv["printed_total"]) if inv.get("printed_total") is not None else None,
        hospital_gstin=inv.get("provider_gstin") or "",
    )


def load_case(doc_id: str, dataset_dir: Optional[str | Path] = None) -> Case:
    """Load a bill (``GEN-02``) or a settlement letter's bill (``SET-01``)."""
    root = Path(dataset_dir) if dataset_dir else default_dataset_dir()
    docs = _manifest(str(root))
    if doc_id not in docs:
        raise KeyError(f"{doc_id} is not a document of the dataset in {root}")
    doc = docs[doc_id]
    bill_id = doc_id
    claim_id = doc_id
    if doc.get("document_type") == "settlement":
        bill_id = doc["document"]["bill_doc_id"]
        claim_id = doc["document"].get("claim_no") or doc_id
    bill = docs[bill_id]
    if not bill.get("invoices"):
        raise ValueError(f"{bill_id} has no invoice to settle")
    claim = claim_from_invoice(bill["invoices"][0], claim_id)

    split, case_id = bill["split"], bill["case_id"]
    policies = {canonical_policy_no(p["policy_no"]): p for p in _for_case(_json(root, split, "policies.json"), case_id)}
    key = canonical_policy_no(claim.policy_no)        # the bill may print look-alike characters
    if key not in policies:
        raise KeyError(f"policy {claim.policy_no} is not in {split}/reference/policies.json")
    policy = policy_from_dict(policies[key])
    history = tuple(past_claim_from_dict(c) for c in _for_case(_json(root, split, "claim_history.json"), case_id)
                    if same_policy(c["policy_no"], policy.policy_no))
    rules = load_rules(root / "policy_rules.json")
    return Case(claim, policy, rules, history, bill_id)


def load_letter(doc_id: str, dataset_dir: Optional[str | Path] = None) -> SettlementLetter:
    """The insurer's letter for ``SET-xx`` as the document reader would extract it.

    Only what is printed on the letter is used: particulars, amount, reason,
    co-pay, amount paid and the rejection reason. The expected verdicts and
    amounts in the same manifest entry are NOT copied.
    """
    root = Path(dataset_dir) if dataset_dir else default_dataset_dir()
    doc = _manifest(str(root))[doc_id]
    if doc.get("document_type") != "settlement":
        raise ValueError(f"{doc_id} is not a settlement letter")
    s = doc["document"]
    rows = tuple(
        LetterRow(row_id=f"R{i}", particulars=r["particulars"], amount=D(r["amount"]), reason=r.get("reason") or "")
        for i, r in enumerate(s.get("insurer_deductions") or [], start=1)
    )
    return SettlementLetter(
        letter_id=s.get("claim_no") or doc_id,
        letter_type=s.get("letter_type") or "settlement",
        claimed_amount=D(s["claimed_amount"]),
        rows=rows,
        paid_amount=D(s["insurer_paid"]),
        copay_amount=D(s["insurer_copay"]) if s.get("insurer_copay") is not None else None,
        rejection_reason=s.get("rejection_reason") or "",
    )


def answer_key(doc_id: str, dataset_dir: Optional[str | Path] = None) -> dict:
    """The expected outcome recorded for a settlement letter. For tests and evaluation only."""
    root = Path(dataset_dir) if dataset_dir else default_dataset_dir()
    return _manifest(str(root))[doc_id]["document"]
