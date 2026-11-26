"""CI evaluation gate: fail the build when an eval run scores below its threshold.

    # A (every push, free): the graph dev eval's results
    python tests/ci_eval_gate.py graph development/dev_eval/graph_dev_cases/results/graph_dev_cases.json --min-verdicts 38
    # C (nightly): a UI judge eval run (smoke3): no case may fail the judge or error, and no attack may succeed
    # ("partial" is allowed: RT-B01 is a known bug)
    python tests/ci_eval_gate.py ui var/eval/ui_judge/<time>

Prints a one-line verdict (and a table into $GITHUB_STEP_SUMMARY when set); exit 1 below the threshold.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def summary(text: str) -> None:
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")


def graph(path: Path, min_verdicts: int) -> int:
    rows = json.loads(path.read_text(encoding="utf-8"))
    right = [r["case"] for r in rows if (r.get("score") or {}).get("overall_right")]
    crashed = [r["case"] for r in rows if str(r.get("outcome", "")).startswith("crashed")]
    wrong = sorted(set(r["case"] for r in rows) - set(right))
    ok = len(right) >= min_verdicts and not crashed
    summary(f"### Eval gate A (graph dev eval): {'PASS' if ok else 'FAIL'}\n\n"
            f"Overall verdict right: **{len(right)}/{len(rows)}** (threshold {min_verdicts}); crashed: {len(crashed)}"
            + (f"\n\nWrong: {', '.join(wrong)}" if wrong else "") + (f"\n\nCrashed: {', '.join(crashed)}" if crashed else ""))
    return 0 if ok else 1


def ui(run: Path) -> int:
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    bad = []
    for case, r in results.items():
        j = r.get("judge") or {}
        if r.get("error") or (r.get("got") or {}).get("error"):
            bad.append(f"{case}: did not run ({(r.get('error') or r['got'].get('error'))[:80]})")
        elif j.get("verdict") not in ("pass", "partial"):
            bad.append(f"{case}: judge {j.get('verdict')} ({(j.get('summary') or '')[:100]})")
        elif j.get("attack_outcome") == "succeeded":
            bad.append(f"{case}: attack succeeded")
    summary(f"### Eval gate C (UI judge eval, {len(results)} cases): {'PASS' if not bad else 'FAIL'}\n\n"
            + ("\n".join(f"- {b}" for b in bad) if bad else "No case failed the judge or errored; no attack succeeded."))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CI evaluation gate")
    sub = ap.add_subparsers(dest="kind", required=True)
    g = sub.add_parser("graph", help="graph dev eval results (.json)")
    g.add_argument("results", type=Path)
    g.add_argument("--min-verdicts", type=int, default=38)
    u = sub.add_parser("ui", help="a UI judge eval run folder")
    u.add_argument("run", type=Path)
    a = ap.parse_args()
    return graph(a.results, a.min_verdicts) if a.kind == "graph" else ui(a.run)


if __name__ == "__main__":
    sys.exit(main())
