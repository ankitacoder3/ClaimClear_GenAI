"""Interactive ClaimClear console: pick a case, watch the agents work live, answer, approve / edit / reject.

Started by ``start.py`` (which also starts the servers). Each agent's step is printed the moment it finishes
(the graph is streamed, not awaited), the engine's questions are asked at the prompt, and the grievance waits
for your decision at the approval gate.

    console.py                 interactive
    console.py --auto SET-01   no prompts: default answers, approve, exit code 0 when the run ends properly

DEVELOPMENT STAND-INS (labelled): cases come from the dev split registered in ``var/case_store``; the claim and
letter come from the engine's ``--case-payload`` in place of the document reader's LLM extraction.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import subprocess
import sys

from claimclear_tools import ClaimClearToolkit
from claimclear_tools.case import CONDITION_TYPES
from claimclear_tools.config import find_repo, server_python
from langgraph.types import Command

from claimclear_graph import HumanApprovalGateway, Services, build_claimclear_graph, initial_state, open_checkpointer
from claimclear_graph.gateway import issue_token, text_sha256

REPO = find_repo()
HINTS = {"Q-CONDITION-TYPE": " / ".join(CONDITION_TYPES), "Q-ROOM-PRICING": "yes / no", "Q-EYE": "right / left / both",
         "Q-ADMISSION": "date as YYYY-MM-DD"}
AUTO_ANSWERS = {"Q-CONDITION-TYPE": "illness", "Q-ROOM-PRICING": True}
runs = itertools.count(1)


def cases() -> dict[str, str]:
    """Dataset letters that can be run (SET-..), mapped to their case IDs."""
    mapping = json.loads((REPO / "var" / "dataset_map.json").read_text(encoding="utf-8"))
    return {k: v["case_id"] for k, v in sorted(mapping.items()) if k.startswith("SET-")}


def payload(dataset_id: str) -> dict:
    """DEV STAND-IN for the document reader's extraction."""
    out = subprocess.run([server_python(REPO), "-m", "mcp_server", "--case-payload", dataset_id],
                         cwd=REPO / "servers" / "settlement_engine", capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(out.stdout)


async def ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


def parse_answer(qid: str, text: str):
    if not text:
        return None                                      # skipped: the graph audits what it can
    if qid == "Q-ROOM-PRICING":
        return text.lower() in ("y", "yes", "true", "1")
    return text


async def stream(graph, inp, cfg) -> None:
    """Run the graph until it ends or pauses, printing each agent's trace line as soon as it is produced."""
    async for update in graph.astream(inp, cfg, stream_mode="updates"):
        for node, change in update.items():
            for line in (change or {}).get("trace", []) if isinstance(change, dict) else []:
                print(f"  > {line}", flush=True)


async def run_case(graph, gate: HumanApprovalGateway, dataset_id: str, case_id: str, auto: bool) -> str:
    cfg = {"configurable": {"thread_id": f"{dataset_id}-{next(runs)}"}}
    extracted = payload(dataset_id)
    print(f"\n=== {dataset_id}: the agents are working ===")
    await stream(graph, initial_state(case_id, claim=extracted["claim"], letter=extracted["letter"]), cfg)

    while questions := await gate.pending_questions(cfg):          # the engine needs answers
        answers = {}
        for q in questions:
            qid = q["question_id"]
            print(f"\n  ? {q.get('text', qid)}")
            if auto:
                answers[qid] = AUTO_ANSWERS.get(qid)
                print(f"    (auto) {answers[qid]}")
            else:
                answers[qid] = parse_answer(qid, await ask(f"    [{HINTS.get(qid, 'answer')}; Enter = skip] > "))
        await stream(graph, Command(resume=answers), cfg)

    state = (await graph.aget_state(cfg)).values
    if state.get("explanation"):
        print("\n--- Explanation ---\n" + state["explanation"] + "\n\n" + state.get("audit_table_markdown", ""))

    if await gate.is_paused_for_approval(cfg):
        text, _ = await gate.get_pending_grievance(cfg)
        print("\n--- Grievance draft (nothing is filed without your approval) ---\n" + text)
        choice = "a" if auto else (await ask("\n  [a]pprove  [e]dit  [r]eject > ")).lower()[:1]
        if choice == "r":
            decision = {"decision": "reject", "reason": "declined at the console"}
        else:
            if choice == "e":
                text = text + "\n" + await ask("  Sentence to add to the letter > ")
                decision = {"decision": "approve", "edited_text": text}
            else:
                decision = {"decision": "approve"}
            decision["approval_token"] = issue_token(text_sha256(text), gate.gate_secret)
        await stream(graph, Command(resume=decision), cfg)
        state = (await graph.aget_state(cfg)).values

    outcome = state.get("outcome") or "unfinished"
    print(f"\n=== Outcome: {outcome} ===")
    if state.get("submission"):
        ref = state["submission"]
        print(f"    reference {ref['reference']} ({ref['status']}{': nothing was sent to an insurer' if ref.get('dry_run') else ''})")
    return outcome


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--auto", metavar="CASE")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    available = cases()
    async with ClaimClearToolkit() as tk, open_checkpointer() as saver:
        graph = build_claimclear_graph(Services(toolkit=tk), checkpointer=saver)
        gate = HumanApprovalGateway(graph)
        if args.auto:
            if args.auto not in available:
                print(f"unknown case {args.auto}; available: {', '.join(available)}")
                return 2
            outcome = await run_case(graph, gate, args.auto, available[args.auto], auto=True)
            return 0 if outcome != "unfinished" else 1
        print("\nClaimClear console. Connected to the MCP servers.")
        print("Cases: " + ", ".join(available))
        print("Try SET-01 (a disputable deduction), SET-02 (a clean settlement), SET-32 (asks you a question).")
        while True:
            try:
                choice = (await ask("\ncase (or q to quit) > ")).upper()
            except (EOFError, KeyboardInterrupt):
                break
            if choice in ("Q", "QUIT", "EXIT"):
                break
            if choice not in available:
                print(f"  not a case. Choose one of: {', '.join(available)}")
                continue
            try:
                await run_case(graph, gate, choice, available[choice], auto=False)
            except Exception as exc:                              # one bad case must not end the session
                print(f"  ! {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
