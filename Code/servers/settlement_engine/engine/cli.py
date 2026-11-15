"""Command line for the engine and the matcher.

    python -m engine.cli SET-01                 # policy-correct settlement
    python -m engine.cli SET-01 --audit         # verdict on every row of the insurer's letter
    python -m engine.cli GEN-02 --json          # full settlement as JSON
    python -m engine.cli SET-01 --audit --json  # full audit as JSON
    python -m engine.cli --hypotheses           # list the hypothesis library

Run from ``servers/settlement_engine``.
"""

from __future__ import annotations

import argparse
import json
import sys

from .dataset import load_case, load_letter
from .engine import _inr, compute_settlement
from .hypotheses import list_hypotheses
from .matcher import audit_letter


def _print_settlement(doc_id, case, result, out) -> None:
    out.write(f"{doc_id} (bill {case.bill_doc_id}, policy {case.policy.policy_no}, "
              f"SI {_inr(case.policy.sum_insured)})\n")
    out.write(f"Status: {result.status.value}\n")
    out.write(f"Claimed: {_inr(result.claimed_amount)}\n")
    for d in result.deductions:
        out.write(f"  - {d.description}: {_inr(d.amount)}   [{d.formula}]  ({d.rule_ref})\n")
    if result.payable_amount is not None:
        out.write(f"Admissible: {_inr(result.admissible_amount)}\n")
        out.write(f"Co-pay: {_inr(result.copay_amount)}\n")
        out.write(f"Payable under the policy: {_inr(result.payable_amount)}\n")
    for q in result.questions:
        out.write(f"QUESTION {q.question_id}: {q.text}\n")
    for w in result.warnings:
        out.write(f"WARNING: {w}\n")


def _print_audit(doc_id, audit, out) -> None:
    out.write(f"{doc_id}: audit of letter {audit.letter_id}\n")
    for r in audit.rows:
        out.write(f"\n[{r.row_id}] {r.particulars}\n")
        out.write(f"    kind {r.kind.value} | insurer {_inr(r.insurer_amount)} | policy "
                  f"{'?' if r.policy_amount is None else _inr(r.policy_amount)} | verdict {r.verdict.value}"
                  f"{' | method ' + r.method if r.method else ''}\n")
        out.write(f"    {r.explanation}\n")
    out.write("\n")
    if audit.policy_payable is not None:
        out.write(f"Payable under the policy: {_inr(audit.policy_payable)}\n")
    out.write(f"Insurer paid:             {_inr(audit.insurer_paid)}\n")
    if audit.gap is not None:
        out.write(f"May be disputable:        {_inr(audit.disputable_amount)}\n")
        out.write(f"Can't be checked:         {_inr(audit.unverified_amount)}\n")
        if audit.overpaid_amount:
            out.write(f"Paid above the policy:    {_inr(audit.overpaid_amount)}\n")
    for d in audit.policy_deductions_not_on_letter:
        out.write(f"NOTE the policy allows a deduction the letter doesn't show: {d}\n")
    for q in audit.questions:
        out.write(f"QUESTION {q.question_id}: {q.text}\n")
    for w in audit.warnings:
        out.write(f"WARNING: {w}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClaimClear settlement engine and matcher.")
    parser.add_argument("doc_id", nargs="?", help="bill ID (e.g. GEN-02) or settlement letter ID (e.g. SET-01)")
    parser.add_argument("--audit", action="store_true", help="audit the insurer's letter (SET-xx only)")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--hypotheses", action="store_true", help="list the hypothesis library and exit")
    parser.add_argument("--dataset", help="path to data/dataset (default: repo copy or $CLAIMCLEAR_DATASET_DIR)")
    args = parser.parse_args(argv)
    out = sys.stdout

    if args.hypotheses:
        for h in list_hypotheses():
            mark = "correct" if h.correct else ("method " if h.method_only else "wrong  ")
            out.write(f"{h.kind.value:15} {mark}  {h.hypothesis_id:30} {h.title}\n")
        return 0
    if not args.doc_id:
        parser.error("doc_id is required unless --hypotheses is given")

    case = load_case(args.doc_id, args.dataset)
    if args.audit:
        audit = audit_letter(load_letter(args.doc_id, args.dataset), case.claim, case.policy, case.rules, case.history)
        if args.json:
            json.dump(audit.to_dict(), out, indent=2, ensure_ascii=False)
            out.write("\n")
        else:
            _print_audit(args.doc_id, audit, out)
        return 0

    result = compute_settlement(case.claim, case.policy, case.rules, case.history)
    if args.json:
        json.dump(result.to_dict(), out, indent=2, ensure_ascii=False)
        out.write("\n")
    else:
        _print_settlement(args.doc_id, case, result, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
