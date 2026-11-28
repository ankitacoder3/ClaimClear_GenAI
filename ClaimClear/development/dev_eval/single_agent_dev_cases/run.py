"""Every development case through the **single agent** (E1's C1), scored like the fixed workflow and the graph.

    .venv-agents/bin/python development/dev_eval/single_agent_dev_cases/run.py                      # all 42 dev cases, servers over stdio
    .venv-agents/bin/python development/dev_eval/single_agent_dev_cases/run.py --only syn-dev-005 gen-dev-147e01
    .venv-agents/bin/python development/dev_eval/single_agent_dev_cases/run.py --http               # against scripts/dev_servers.py

The three versions of the review now each have a runner here, scored by ``dev_cases/run.py:score`` against the same
answers:

    1  no LLM / agents   development/dev_eval/dev_cases/run.py                 the C0 fixed workflow (Member 2)
    2  single agent      development/dev_eval/single_agent_dev_cases/run.py    this file (E1's C1)
    3  multi-agent       development/dev_eval/graph_dev_cases/run.py           the ClaimClear graph (Member 3)

The single agent is one LLM with every read tool (``SINGLE_AGENT``, no write tool), deciding its own steps
(``e1_architectures/single_agent.py`` in Member 1's E1 add-on, imported unchanged). It **reads the documents itself**:
no stand-in claim or letter is handed to it, so the like-for-like comparison is ``graph_dev_cases/run.py
--llm-extract``, where the graph's document reader reads with the model too. Every figure is still the engine's: the
agent's result is the last ``audit_settlement_letter`` it obtained.

Same budget as E1 (``run_review``: 30 model calls, 80 tool calls, 600 s per case; ``CLAIMCLEAR_E1_BUDGET`` changes it),
with model calls, tokens, cost, time and policy violations recorded per case. Needs the app's model: a local LLM
(``CLAIMCLEAR_LLM_BASE_URL``) or ``OPENROUTER_API_KEY``. The engine's questions are left unanswered and nothing is filed.

Writes ``development/dev_eval/single_agent_dev_cases/results/single_agent_dev_cases.md`` and ``.json``. Held-out cases
are never read.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import median

from claimclear_tools import ClaimClearToolkit

from claimclear_graph import AuditLog

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
REPO = HERE.parents[2]                                                    # ClaimClear/
E1 = REPO / "additional_resources" / "member1_evaluation_golden_dataset" / "handover_code" / "E1"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def c0_module():
    """Member 2's fixed-workflow run, imported for its dataset preparation and scoring."""
    return _load("eval_dev_cases_run", HERE.parent / "dev_cases" / "run.py")


def graph_module():
    """Member 3's graph run, imported for ``as_c0_result`` (the state in the shape the scorer reads)."""
    return _load("eval_graph_dev_cases_run", HERE.parent / "graph_dev_cases" / "run.py")


def architectures():
    """E1's three architectures (only C1 is used here)."""
    if str(E1) not in sys.path:
        sys.path.insert(0, str(E1))
    import e1_architectures
    return e1_architectures


def llm_from_env():
    """The app's model (a local LLM first, then OpenRouter), or exit with a clear message."""
    from claimclear_graph.chat import chat_model_from_env
    llm = chat_model_from_env()
    if llm is None:
        raise SystemExit("the single agent needs a model: a local LLM (CLAIMCLEAR_LLM_BASE_URL, e.g. from start_llm) "
                         "or OPENROUTER_API_KEY; see .env.example")
    return llm


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def report(rows: list[dict], c0: dict, model: str) -> str:
    def rate(key):
        have = [r["score"][key] for r in rows if key in r["score"]]
        return f"{sum(have)}/{len(have)}" if have else "-"
    lines = ["# Single agent (E1's C1): development cases", "",
             f"Every dev case through one LLM agent with every read tool ({model}), reading the documents itself, "
             "scored with `development/dev_eval/dev_cases/run.py:score` (the same answers and rules as the C0 and "
             "graph runs). Questions left unanswered; nothing filed.", "",
             "| Cases | Ran to the end (audit produced) | Overall verdict right | Row verdicts right | Payable right (±₹1) | "
             "Disputable right (±₹1) | Same overall verdict as C0 |", "|---|---|---|---|---|---|---|"]
    with_rows = [r["score"] for r in rows if "rows" in r["score"]]
    row_rate = f"{sum(s['rows_right'] for s in with_rows)}/{sum(s['rows'] for s in with_rows)}" if with_rows else "-"
    same = [r for r in rows if r["case"] in c0]
    agree = sum(1 for r in same if r["score"].get("engine_overall") == c0[r["case"]].get("engine_overall"))
    lines.append(f"| {len(rows)} | {sum(1 for r in rows if r['audited'])} | {rate('overall_right')} | {row_rate} | "
                 f"{rate('payable_right')} | {rate('disputable_right')} | {agree}/{len(same)} |")
    used = [r["usage"] for r in rows]
    secs = [u.get("seconds", 0) for u in used]
    cost = sum(u.get("cost_usd", 0) or 0 for u in used)
    errors = [r for r in rows if r.get("error")]
    lines += ["", f"Cost and effort: {sum(u.get('model_calls', 0) for u in used)} model calls, "
                  f"{sum(u.get('input_tokens', 0) for u in used)} input and {sum(u.get('output_tokens', 0) for u in used)} "
                  f"output tokens, US${cost:.4f} in all (US${cost / max(len(rows), 1):.4f} per case), "
                  f"{sum(u.get('tool_calls', 0) for u in used)} tool calls. Seconds per case: median "
                  f"{median(secs) if secs else 0:.1f}, p95 {p95(secs):.1f}. Errors or timeouts: {len(errors)}. "
                  f"Policy violations: {sum(len(r['policy_violations']) for r in rows)}.",
              f"Outcomes: {dict(Counter(r['outcome'] for r in rows))}.",
              "", "| Case | Outcome | Expected | Single agent | C0 | Model calls | Tool calls | Seconds | Violations |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s, u = r["score"], r["usage"]
        mark = "✓" if s.get("overall_right") else "✗"
        lines.append(f"| {r['case']} | {r['outcome']} | {s.get('expected_overall')} | {s.get('engine_overall')} {mark} | "
                     f"{(c0.get(r['case']) or {}).get('engine_overall', '-')} | {u.get('model_calls', 0)} | "
                     f"{u.get('tool_calls', 0)} | {u.get('seconds', 0)} | {len(r['policy_violations'])} |")
    for r in rows:
        if r["policy_violations"] or r.get("error"):
            lines.append(f"\n- {r['case']}: " + "; ".join([*([r["error"]] if r.get("error") else []),
                                                            *r["policy_violations"]]))
    return "\n".join(lines) + "\n"


async def main(argv=None, llm=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--http", action="store_true", help="use the servers started by scripts/dev_servers.py")
    p.add_argument("--only", nargs="*", help="dataset case IDs to run")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args(argv)
    llm = llm if llm is not None else llm_from_env()
    from claimclear_graph.chat import describe_model
    arch, c0, as_c0_result = architectures(), c0_module(), graph_module().as_c0_result
    c0.WORK.mkdir(parents=True, exist_ok=True)
    mapping, _extracted = c0.prepare()                     # the stand-in readings are not given to the agent
    answers = {a.stem: json.loads(a.read_text(encoding="utf-8"))
               for a in sorted((c0.DATASET / c0.SPLIT / "answers").glob("*.json"))}
    c0_scores = {}
    c0_json = HERE.parent / "dev_cases" / "results" / "dev_cases.json"
    if c0_json.exists():
        c0_scores = {r["case"]: r["score"] for r in json.loads(c0_json.read_text(encoding="utf-8"))}
    names = [n for n in answers if not args.only or n in args.only]
    budget = arch.Budget.from_env()
    rows = []
    log = AuditLog()
    async with ClaimClearToolkit(mode="http" if args.http else None, tool_interceptors=[log]) as tk:
        for name in names:
            case_id = c0.store_case_id(name, answers[name], mapping)
            try:
                st = await arch.run_review("c1", tk, llm, case_id, budget=budget)
            except Exception as exc:                           # recorded in the report, never hidden
                st = {"outcome": f"crashed: {type(exc).__name__}", "error": str(exc), "usage": {},
                      "policy_violations": [], "trace": [str(exc)]}
            row = {"case": name, "outcome": st.get("outcome"), "audited": bool(st.get("letter_audit")),
                   "agent_verdict": st.get("agent_verdict"), "error": st.get("error"), "usage": st.get("usage") or {},
                   "policy_violations": st.get("policy_violations") or [],
                   "score": c0.score(answers[name], as_c0_result(st)), "trace": st.get("trace", [])}
            rows.append(row)
            print(f"{name:<18} {str(row['outcome']):<20} {row['score'].get('engine_overall')}")
    text = report(rows, c0_scores, describe_model(llm))
    stem = "single_agent_dev_cases"
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
