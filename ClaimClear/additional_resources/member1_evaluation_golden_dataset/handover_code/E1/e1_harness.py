"""The team's UI eval harness (``ui_chainlit/ui_judge_eval.py``) with E1's architecture switch, from outside.

``ui_judge_eval.py`` is not changed: this script imports it, replaces its ``review`` step for this process with
``review_e1`` (the chosen configuration, metered), and then runs its ``main`` with every other option as it is.

    cd ClaimClear                 (servers up: python start.py --servers-only; model in .env)
    .venv-agents/Scripts/python additional_resources/member1_evaluation_golden_dataset/handover_code/E1/e1_harness.py --bundle dev --config c1
    ... e1_harness.py RT-N-004 --config c0 --no-judge --out var/eval/e1/try

``--config c0|c1|c2`` (default ``CLAIMCLEAR_ARCHITECTURE``, else c2) and ``--out DIR`` (where the run goes; default
the harness's own ``var/eval/ui_judge/<time>``) are this script's; everything else goes to ``ui_judge_eval.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]                                   # ClaimClear/
UI = REPO / "ui_chainlit"
for p in (str(HERE), str(UI)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("CHAINLIT_APP_ROOT", str(UI))

import e1_architectures as arch  # noqa: E402
import ui_judge_eval  # noqa: E402  (the team's harness, used as it is)


async def review_e1(app: dict, case_id: str, flags: list[str] = ()) -> tuple[dict, dict]:
    """In place of ``ui_judge_eval.review``: the review by the chosen architecture, with the same model, tools and
    budget for all three; returns what ``review`` returns (final state, fields for the checks and the judge) plus
    the configuration, its usage, policy violations and review time. A stopped run (timeout, budget) is an error."""
    config = arch.chosen()
    st = await arch.run_review(config, app["toolkit"], app["llm"], case_id, flags=flags)
    got = {"architecture": config, "trace": st.get("trace", []), "questions_asked": st.get("questions_asked", []),
           "grievance_offered": st.get("grievance_offered", False), "usage": st.get("usage"),
           "policy_violations": st.get("policy_violations", []),
           "review_seconds": (st.get("usage") or {}).get("seconds"), **ui_judge_eval.summarise(st)}
    if st.get("error"):
        got["error"] = st["error"]                       # the harness then skips the checks and the judge
    return st, got


def install() -> None:
    """Plug ``review_e1`` into the harness (this process only)."""
    ui_judge_eval.review = review_e1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ui_judge_eval.py with E1's --config", add_help=False)
    ap.add_argument("--config", choices=arch.CONFIGS)
    ap.add_argument("--out")
    mine, rest = ap.parse_known_args(argv)
    if "-h" in rest or "--help" in rest:
        print(__doc__)
    if mine.config:
        os.environ[arch.ENV] = mine.config
    arch.chosen()                                        # fail early on a bad CLAIMCLEAR_ARCHITECTURE
    install()
    if not mine.out:
        return asyncio.run(ui_judge_eval.main(rest))
    out = Path(mine.out)
    parking = out.parent / f".{out.name}.running"       # the harness names its folder by time: park it, then move
    shutil.rmtree(parking, ignore_errors=True)
    parking.mkdir(parents=True)
    ui_judge_eval.OUT = parking
    try:
        code = asyncio.run(ui_judge_eval.main(rest))
    finally:
        made = [d for d in parking.iterdir() if d.is_dir()]
        if made:
            shutil.rmtree(out, ignore_errors=True)
            shutil.move(str(made[0]), str(out))
        shutil.rmtree(parking, ignore_errors=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
