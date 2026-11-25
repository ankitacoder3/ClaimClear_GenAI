"""How well a judge agrees with hand labels (or with another judge): Cohen's kappa on pass / partial / fail.
No model calls. The course guide asks to check the judge on 20+ hand-labelled outputs and report kappa.

    # hand labels: a CSV with columns case,verdict  (verdict = pass | partial | fail)
    ../.venv-agents/Scripts/python judge_kappa.py labels.csv ../var/eval/ui_judge/<time>/rejudged_<model>.json
    # two judges on the same run
    ../.venv-agents/Scripts/python judge_kappa.py ../var/eval/ui_judge/<time>/results.json ../var/eval/ui_judge/<time>/rejudged_<model>.json

A ``.json`` is a run's results (``results.json``) or a re-judged copy (``rejudged_<model>.json``); a ``.csv`` holds
hand labels. Only cases graded by both are compared.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

LABELS = ("pass", "partial", "fail")


def verdicts(path: Path) -> dict[str, str]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            return {r["case"].strip(): r["verdict"].strip().lower() for r in csv.DictReader(f)
                    if r.get("verdict", "").strip().lower() in LABELS}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v["judge"]["verdict"] for k, v in data.items()
            if isinstance(v.get("judge"), dict) and v["judge"].get("verdict") in LABELS}


def kappa(a: dict[str, str], b: dict[str, str]) -> tuple[float, float, int]:
    """(kappa, raw agreement, cases compared) over the cases both graded."""
    cases = sorted(set(a) & set(b))
    n = len(cases)
    if not n:
        return 0.0, 0.0, 0
    agree = sum(a[c] == b[c] for c in cases) / n
    ca, cb = Counter(a[c] for c in cases), Counter(b[c] for c in cases)
    chance = sum(ca[l] * cb[l] for l in LABELS) / (n * n)
    return (1.0 if chance == 1 else (agree - chance) / (1 - chance)), agree, n


def main() -> None:
    ap = argparse.ArgumentParser(description="Cohen's kappa between hand labels and a judge, or two judges")
    ap.add_argument("first", type=Path, help="labels.csv (case,verdict) or a results/rejudged .json")
    ap.add_argument("second", type=Path, help="a results/rejudged .json")
    a = ap.parse_args()
    k, agree, n = kappa(verdicts(a.first), verdicts(a.second))
    print(f"cases compared: {n} | raw agreement: {agree:.0%} | Cohen's kappa: {k:.2f}")


if __name__ == "__main__":
    main()
