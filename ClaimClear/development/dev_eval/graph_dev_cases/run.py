"""Every development case through the **multi-agent graph** (Member 3), scored like the fixed workflow.

    .venv-agents/bin/python development/dev_eval/graph_dev_cases/run.py                     # all 42 dev cases, servers over stdio  (# Project restructuring #1)
    .venv-agents/bin/python development/dev_eval/graph_dev_cases/run.py --only SET-01 gen-dev-147e01  (# Project restructuring #1)
    .venv-agents/bin/python development/dev_eval/graph_dev_cases/run.py --http              # against scripts/dev_servers.py  (# Project restructuring #1)

``development/dev_eval/dev_cases/run.py`` (Member 2) drives the servers as a fixed C0 workflow . This run sends the same  (# Project restructuring #1)
cases, with the same development stand-ins (upload into a scratch store; claim/letter from
``development/dev_eval/dev_cases/extract.py``), through ``claimclear_graph``: supervisor, document reader, policy  (# Project restructuring #1)
analyst, auditor, critic (both reviews), explainer and grievance agent. It reuses that script's
``prepare``, ``store_case_id`` and ``score``, so both runs are scored identically against the answers.

No person is present, so: the engine's questions are left **unanswered** (the graph then audits what
it can, as C0 does), and a grievance waiting at the approval gate is **rejected** (nothing is filed).

**LLM extraction** (``--llm-extract``): the claim and the letter are *not* handed to the graph; the document
reader extracts them from the documents with an LLM (``claimclear_graph.checked_extraction``), and each
extraction is compared with the stand-in's (bill total, line count, letter rows and their amounts, paid amount).
Needs the app's model: a local LLM (``CLAIMCLEAR_LLM_BASE_URL``) or ``OPENROUTER_API_KEY``; the model can be
overridden with ``$CLAIMCLEAR_EXTRACTION_MODEL``. Results go to
``results/graph_dev_cases_llm.md`` so they sit next to the stand-in run.

Writes ``development/dev_eval/graph_dev_cases/results/graph_dev_cases.md`` and ``.json``. Held-out cases are never read.  (# Project restructuring #1)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path

from claimclear_tools import ClaimClearToolkit, signals

from claimclear_graph import AuditLog, HumanApprovalGateway, Services, build_claimclear_graph, initial_state

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def c0_module():
    """Member 2's fixed-workflow run, imported for its dataset preparation and scoring."""
    spec = importlib.util.spec_from_file_location("eval_dev_cases_run", HERE.parent / "dev_cases" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def as_c0_result(state: dict) -> dict:
    """The graph's final state in the shape ``development/dev_eval/dev_cases/run.py:score`` reads."""  # Project restructuring #1
    a, rows = state.get("letter_audit"), state.get("row_audits") or {}
    out: dict = {"route": state.get("outcome") or state.get("route"), "steps": {}}
    if a:
        out["audit"] = {"policy_payable": a["policy_payable"], "insurer_paid": a["insurer_paid"],
                        "disputable": a["disputable_amount"], "unverified": a["unverified_amount"],
                        "rows": {k: {"verdict": v["verdict"]} for k, v in rows.items()},
                        "letter_type": (state.get("letter") or {}).get("letter_type"),
                        "bill_inconsistencies": [d["description"] for d in signals.bill_inconsistencies(a)]}
    return out


def _amount(v) -> float:
    """An amount for scoring; an LLM may write it as text ("-₹550.00", "Rs. 1,200"). Unreadable counts as 0."""
    if isinstance(v, str):
        v = "".join(ch for ch in v if ch.isdigit() or ch in ".-")
    try:
        return round(float(v or 0), 2)
    except ValueError:
        return 0.0


def compare_extraction(got: dict | None, want: dict) -> dict:
    """An LLM extraction against the stand-in's, on the fields the engine's figures depend on."""
    if not got or not got.get("claim") or not got.get("letter"):
        return {"extracted": False}
    gc, wc, gl, wl = got["claim"], want["claim"], got["letter"], want["letter"]
    want_rows = {_amount(r["amount"]) for r in wl.get("rows", [])}
    got_rows = {_amount(r.get("amount")) for r in gl.get("rows", [])}
    checks = {
        "bill_total": abs(sum(_amount(x.get("amount")) for x in gc.get("lines", []))
                          - sum(_amount(x["amount"]) for x in wc["lines"])) < 1,
        "line_count": len(gc.get("lines", [])) == len(wc["lines"]),
        "letter_rows": got_rows == want_rows,
        "paid_amount": abs(_amount(gl.get("paid_amount")) - _amount(wl.get("paid_amount"))) < 1,
        "policy_no": gc.get("policy_no") == wc.get("policy_no"),
    }
    return {"extracted": True, **checks, "all_right": all(checks.values())}


def llm_from_env():
    """The extraction model: the configured local LLM or OpenRouter (as in the app), or exit with a clear message."""
    import os
    from claimclear_graph.chat import chat_model_from_env
    llm = chat_model_from_env()
    if llm is None:
        raise SystemExit("--llm-extract needs a local LLM (CLAIMCLEAR_LLM_BASE_URL) or OPENROUTER_API_KEY; "
                         "see .env.example")
    model = os.environ.get("CLAIMCLEAR_EXTRACTION_MODEL")
    return llm.model_copy(update={"model_name": model, "streaming": False}) if model else llm


async def run_one(tk, case_id: str, extracted: dict, name: str, extractor=None) -> dict:
    """One case through the graph. With ``extractor`` the stand-in's claim/letter are withheld from the graph."""
    graph = build_claimclear_graph(Services(toolkit=tk, extractor=extractor))
    gate = HumanApprovalGateway(graph)
    cfg = {"configurable": {"thread_id": name}}
    t0 = time.perf_counter()
    given = {} if extractor else {"claim": extracted.get("claim"), "letter": extracted.get("letter")}
    state = await graph.ainvoke(initial_state(case_id, **given), cfg)
    asked: list[str] = []
    for _ in range(3):                                         # unanswered questions: audit what can be audited
        qs = await gate.pending_questions(cfg)
        if not qs:
            break
        asked += [q["question_id"] for q in qs]
        state = await gate.answer_questions(cfg, {q["question_id"]: None for q in qs})
    offered = await gate.is_paused_for_approval(cfg)
    if offered:
        state = await gate.reject(cfg, "evaluation run: nothing is filed")
    return {"state": state, "asked": asked, "grievance_offered": offered, "seconds": round(time.perf_counter() - t0, 2)}


def report(rows: list[dict], c0: dict) -> str:
    def rate(key):
        have = [r["score"][key] for r in rows if key in r["score"]]
        return f"{sum(have)}/{len(have)}" if have else "-"
    lines = ["# Multi-agent graph: development cases", "",
             "Every dev case through `claimclear_graph` and the real MCP servers, scored with "
             "`development/dev_eval/dev_cases/run.py:score` (the same answers and rules as the fixed-workflow C0 run)  (# Project restructuring #1). "
             "Questions left unanswered; grievances rejected at the gate (nothing filed).", "",
             "| Cases | Ran to the end (audit produced) | Overall verdict right | Row verdicts right | Payable right (±₹1) | "
             "Disputable right (±₹1) | Same overall verdict as C0 |", "|---|---|---|---|---|---|---|"]
    with_rows = [r["score"] for r in rows if "rows" in r["score"]]
    row_rate = f"{sum(s['rows_right'] for s in with_rows)}/{sum(s['rows'] for s in with_rows)}" if with_rows else "-"
    same = [r for r in rows if r["case"] in c0]
    agree = sum(1 for r in same if r["score"].get("engine_overall") == c0[r["case"]].get("engine_overall"))
    lines.append(f"| {len(rows)} | {sum(1 for r in rows if r['audited'])} | {rate('overall_right')} | {row_rate} | "
                 f"{rate('payable_right')} | {rate('disputable_right')} | {agree}/{len(same)} |")
    lines += ["", f"Outcomes: {dict(Counter(r['outcome'] for r in rows))}. "
                  f"Grievances offered at the gate: {sum(r['grievance_offered'] for r in rows)}. "
                  f"Replans: {sum(r['replans'] for r in rows)}. Critic draft failures: {sum(r['draft_failures'] for r in rows)}.",
              "", "| Case | Outcome | Expected | Graph | C0 | Questions left open | Critic | Seconds |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["score"]
        mark = "✓" if s.get("overall_right") else "✗"
        lines.append(f"| {r['case']} | {r['outcome']} | {s.get('expected_overall')} | {s.get('engine_overall')} {mark} | "
                     f"{(c0.get(r['case']) or {}).get('engine_overall', '-')} | {', '.join(r['asked']) or '-'} | "
                     f"{r['critic']} | {r['seconds']} |")
    return "\n".join(lines) + "\n"


async def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--http", action="store_true", help="use the servers started by scripts/dev_servers.py")
    p.add_argument("--only", nargs="*", help="dataset case IDs to run")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--llm-extract", action="store_true",
                   help="let the document reader's LLM extract claim and letter (needs an API key)")
    args = p.parse_args(argv)
    extractor = None
    if args.llm_extract:
        from claimclear_graph.checked_extraction import make_extractor   # CLAIMCLEAR_READER=classic: the original
        extractor = make_extractor(llm_from_env())
    c0 = c0_module()
    c0.WORK.mkdir(parents=True, exist_ok=True)
    mapping, extracted = c0.prepare()
    answers = {a.stem: json.loads(a.read_text(encoding="utf-8"))
               for a in sorted((c0.DATASET / c0.SPLIT / "answers").glob("*.json"))}
    c0_scores = {}
    c0_json = HERE.parent / "dev_cases" / "results" / "dev_cases.json"
    if c0_json.exists():
        c0_scores = {r["case"]: r["score"] for r in json.loads(c0_json.read_text(encoding="utf-8"))}
    names = [n for n in answers if not args.only or n in args.only]
    rows = []
    log = AuditLog()
    async with ClaimClearToolkit(mode="http" if args.http else None, tool_interceptors=[log]) as tk:
        for name in names:
            case_id = c0.store_case_id(name, answers[name], mapping)
            ex = extracted.get(name, {})
            try:
                res = await run_one(tk, case_id, ex, name, extractor)
            except Exception as exc:                           # recorded in the report, never hidden
                res = {"state": {"outcome": f"crashed: {type(exc).__name__}", "trace": [str(exc)]}, "asked": [],
                       "grievance_offered": False, "seconds": 0}
            st = res["state"]
            trace = st.get("trace", [])
            row = {"case": name, "outcome": st.get("outcome"), "asked": res["asked"], "audited": bool(st.get("letter_audit")),
                   "grievance_offered": res["grievance_offered"], "seconds": res["seconds"],
                   "replans": sum("Supervisor: replan" in t for t in trace),
                   "draft_failures": sum("draft attempt" in t and "FAILED" in t for t in trace),
                   "critic": "passed" if (st.get("critic") or {}).get("passed") else
                             ("-" if not st.get("critic") else "failed"),
                   "score": c0.score(answers[name], as_c0_result(st)), "trace": trace}
            if extractor and "claim" in ex:
                row["extraction"] = compare_extraction({"claim": st.get("claim"), "letter": st.get("letter")}, ex)
            rows.append(row)
            print(f"{name:<18} {str(row['outcome']):<20} {row['score'].get('engine_overall')}")
    text = report(rows, c0_scores)
    if extractor:
        judged = [r["extraction"] for r in rows if "extraction" in r]
        fields = ("bill_total", "line_count", "letter_rows", "paid_amount", "policy_no", "all_right")
        text += ("\n## LLM extraction vs the stand-in\n\n| " + " | ".join(fields) + " |\n|" + "---|" * len(fields) + "\n| "
                 + " | ".join(f"{sum(1 for j in judged if j.get(f))}/{len(judged)}" for f in fields) + " |\n")
    stem = "graph_dev_cases_llm" if extractor else "graph_dev_cases"
    if args.no_write:
        print(text)
    else:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / f"{stem}.md").write_text(text, encoding="utf-8")
        (RESULTS / f"{stem}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str),
                                              encoding="utf-8")
        print(f"wrote {RESULTS / (stem + '.md')} ({len(log.records)} MCP calls)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
