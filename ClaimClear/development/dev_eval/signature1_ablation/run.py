"""E4 Signature 1 ablation: engine + matcher (ON) vs LLM-only (OFF), the same cases and the same scorer.

    .venv-agents/Scripts/python.exe development/dev_eval/signature1_ablation/run.py --signature1 on
    .venv-agents/Scripts/python.exe development/dev_eval/signature1_ablation/run.py --signature1 off
    .venv-agents/Scripts/python.exe development/dev_eval/signature1_ablation/run.py --signature1 both --repeat 3
    CLAIMCLEAR_SIGNATURE1=off .venv-agents/Scripts/python.exe development/dev_eval/signature1_ablation/run.py

Signature problem 1 is "reproduce the insurer's arithmetic" (problem statement, p. 10):

* **ON (proposed, the product):** the settlement engine works out the policy-correct settlement and the matcher
  tries the 51-method hypothesis library on every letter row (``expected_settlement``, ``reproduce_deduction``,
  ``audit_settlement_letter``). Tested code produces every verdict and rupee figure. This is the C0 run of
  ``development/dev_eval/dev_cases/run.py``, called unchanged.
* **OFF (ablation, LLM-only baseline):** the settlement engine and matcher are not called. One LLM call per case
  gets the same claim, letter, policy schedule and claim history plus the policy clauses policy-kb retrieves for
  every letter row, and judges every row itself (verdict, policy amount, disputable amount).

Everything else is the same: dataset, extraction stand-in, policy and history tools, policy-kb retrieval, scorer.
Scored per case against the answer file (read only after the run):

* **Verdict accuracy:** each letter row's verdict (matches_policy / does_not_match_policy / method_matches /
  not_verifiable), plus the overall verdict.
* **Rupee error:** |expected disputable amount - output|, mean and median, and the share within ₹1.
* **False-dispute rate:** rows the answer file calls ``matches_policy`` that the run calls
  ``does_not_match_policy`` (the brief's key safety metric); also cases wrongly called disputable.
* **Cost, latency (median, p95), errors:** LLM tokens and estimated USD, seconds per case, crashes and
  unreadable model answers.

Writes ``results/signature1_<on|off>_<time>.md`` and ``.json`` and adds one line per run to
``results/history.csv``. Held-out cases are read only with ``--split heldout``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib.util
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from claimclear_tools import ClaimClearToolkit, build_case, signals
from claimclear_tools.results import ClaimClearToolError

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
VERDICTS = ("matches_policy", "does_not_match_policy", "method_matches", "not_verifiable")
# OpenRouter list price of openai/gpt-4.1-mini, USD per million tokens (input, output); other models: tokens only
PRICES = {"openai/gpt-4.1-mini": (0.40, 1.60), "gpt-4.1-mini": (0.40, 1.60)}
# Clauses every audit needs besides the ones each letter row points to
STANDARD_QUERIES = ("room rent limit per day", "co-payment percentage", "proportionate deduction",
                    "cataract limit per eye", "non-payable items list", "waiting period", "sum insured")


def c0_module():
    """Member 2's fixed-workflow run (``dev_cases/run.py``): dataset preparation, the ON pipeline and the scorer."""
    spec = importlib.util.spec_from_file_location("eval_dev_cases_run", HERE.parent / "dev_cases" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C0 = c0_module()


def load_dotenv(path: Path) -> None:
    """``KEY=value`` lines of the repository's ``.env`` into the environment (values already set win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# --------------------------------------------------------------------------- OFF: the LLM-only baseline


PROMPT = """You audit an Indian health-insurance settlement letter for the policyholder.
Read the hospital bill, the insurer's settlement letter, the policy schedule, earlier claims and the policy clauses
below, then judge every deduction row yourself. Work out any amounts yourself.

Verdict for each row (use exactly these words):
- matches_policy: the deduction, and its amount, is what the policy requires.
- does_not_match_policy: the policy does not support this deduction or its amount is wrong; the policyholder may
  dispute it.
- method_matches: the method is right but the amount differs only because an earlier figure was wrong
  (for example the co-payment percentage is right but taken on a wrong base).
- not_verifiable: it cannot be checked from these documents.
Row COPAY is the letter's co-payment deduction. Row REJECTION is the insurer's rejection of the whole claim:
matches_policy if the rejection is valid under the policy, does_not_match_policy if it is not.

Also give:
- policy_payable: the total the policy should pay for this claim, in rupees (null if you cannot tell).
- disputable_amount: rupees the policyholder can fairly challenge (what the policy should pay minus what the
  insurer paid, from the rows you call does_not_match_policy or method_matches; 0 if every row matches;
  for a wrongly rejected claim, what the policy should pay).
- unverified_amount: rupees in rows you call not_verifiable (0 if none).
- documents_inconsistent: true only if the bill, letter or schedule contradict each other (different patient,
  policy, dates or totals), with a short reason.

Answer with one JSON object only. Every amount is a plain number (do the arithmetic first; no sums in the JSON):
{{"rows": [{{"row_id": "R1", "verdict": "...", "policy_amount": 0, "reason": "..."}}],
  "policy_payable": 0, "insurer_paid": 0, "disputable_amount": 0, "unverified_amount": 0,
  "documents_inconsistent": false, "inconsistency": ""}}
Include exactly these row_ids: {row_ids}

POLICY SCHEDULE:
{policy}

EARLIER CLAIMS ON THIS POLICY:
{history}

HOSPITAL BILL (claim):
{claim}

SETTLEMENT LETTER:
{letter}

POLICY CLAUSES (retrieved from the policy wording):
{clauses}
"""


def llm_from_env(model: str | None):
    """The app's chat model (local LLM or OpenRouter, as configured in ``.env``), non-streaming, JSON answers."""
    from claimclear_graph.chat import chat_model_from_env
    llm = chat_model_from_env()
    if llm is None:
        raise SystemExit("--signature1 off needs OPENROUTER_API_KEY (or CLAIMCLEAR_LLM_BASE_URL) in .env")
    update = {"streaming": False, "max_tokens": 4000}
    if model:
        update["model_name"] = model
    return llm.model_copy(update=update).bind(response_format={"type": "json_object"})


async def clauses_for(tk: ClaimClearToolkit, letter: dict, wording_uin: str) -> list[dict]:
    """Policy-kb clauses for every letter row (its particulars and reason) and the standard limits, deduplicated."""
    queries = [f"{r.get('particulars', '')} {r.get('reason', '')}".strip()[:300] for r in letter.get("rows", [])]
    if letter.get("rejection_reason"):
        queries.append(letter["rejection_reason"][:300])
    queries += STANDARD_QUERIES
    seen: dict[str, dict] = {}
    for q in queries:
        if not q:
            continue
        found = await tk.search_clauses(q, k=3, wording_uin=wording_uin)
        for hit in found.get("hits", []):
            seen.setdefault(hit["clause_id"], {"clause": hit.get("citation") or hit["clause_id"],
                                               "text": hit["text"][:900]})
    return list(seen.values())


def arithmetic(expr: str) -> float:
    """The value of plain arithmetic (numbers, + - * / and brackets only); anything else raises ValueError."""
    import ast
    import operator
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        raise ValueError(expr)
    return ev(ast.parse(expr.replace(",", ""), mode="eval").body)


# a JSON value the model wrote as a sum ("policy_payable": 77980 - 650 - 180), up to the next , } or newline
SUM_VALUE = re.compile(r'(:\s*)([-\d.\s()+*/,]*\d[-\d.\s()+*/]*[-+*/][-\d.\s()+*/]*\d\)*)(\s*[,}\n])')


def parse_json(text: str) -> dict:
    """The model's JSON; a value written as arithmetic is worked out first (the model's own sum, not ours)."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    body = m.group(0) if m else text
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        fixed = SUM_VALUE.sub(lambda g: f"{g.group(1)}{round(arithmetic(g.group(2)), 2)}{g.group(3)}", body)
        return json.loads(fixed)


def money(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        try:
            return round(arithmetic(v), 2)
        except (ValueError, SyntaxError, ZeroDivisionError):
            v = re.sub(r"(?i)rs\.?|inr|₹|,|\s", "", v)       # "Rs. 1,200" -> 1200; "5% of x" -> None
    try:
        return round(float(v), 2)
    except ValueError:
        return None


async def run_case_llm_only(tk: ClaimClearToolkit, case_id: str, extracted: dict, llm) -> dict:
    """Steps 3-4 exactly as the ON run (policy, history, extraction), then one LLM call instead of the engine."""
    out: dict = {"steps": {}, "route": None, "llm": {}}
    t0 = time.perf_counter()
    wording = await tk.get_policy_wording(case_id)
    try:
        policy = await tk.get_policy(case_id)
        history = await tk.get_claim_history(case_id)
    except ClaimClearToolError as exc:
        out["steps"]["policy"] = {"error": exc.info.code}
        out["route"] = "ask_user_for_policy"
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    if "error" in extracted or "letter" not in extracted:
        out["route"] = "extraction_failed"
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    letter, claim = extracted["letter"], extracted["claim"]
    if claim["policy_no"] != policy["policy_no"] and C0.lookalike(claim["policy_no"], policy["policy_no"]):
        claim = {**claim, "policy_no": policy["policy_no"]}
    try:
        build_case(claim, policy, history)               # the same consistency check as the ON run
    except ValueError as exc:
        out["route"] = "policy_mismatch"
        out["steps"]["extraction"] = str(exc)
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out

    row_ids = signals.rows_to_audit(letter)
    clauses = await clauses_for(tk, letter, wording["wording_uin"])
    prompt = PROMPT.format(row_ids=", ".join(row_ids), policy=json.dumps(policy, default=str),
                           history=json.dumps(history, default=str), claim=json.dumps(claim, ensure_ascii=False),
                           letter=json.dumps(letter, ensure_ascii=False),
                           clauses="\n\n".join(f"[{c['clause']}] {c['text']}" for c in clauses))
    t1 = time.perf_counter()
    msg = await llm.ainvoke(prompt)
    usage = getattr(msg, "usage_metadata", None) or {}
    out["llm"] = {"seconds": round(time.perf_counter() - t1, 2), "input_tokens": usage.get("input_tokens", 0),
                  "output_tokens": usage.get("output_tokens", 0), "clauses": len(clauses)}
    try:
        answer = parse_json(msg.content if isinstance(msg.content, str) else str(msg.content))
    except (json.JSONDecodeError, ValueError):
        out["route"] = "unreadable_llm_answer"
        out["llm"]["raw"] = str(msg.content)[:6000]
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    got = {str(r.get("row_id")): r for r in answer.get("rows", []) if isinstance(r, dict)}
    rows = {}
    for rid in row_ids:
        r = got.get(rid, {})
        v = r.get("verdict") if r.get("verdict") in VERDICTS else "not_verifiable"
        rows[rid] = {"verdict": v, "policy_amount": money(r.get("policy_amount")), "reason": str(r.get("reason", ""))[:300],
                     "missing_from_answer": rid not in got}
    out["audit"] = {
        "policy_payable": money(answer.get("policy_payable")), "insurer_paid": money(answer.get("insurer_paid")),
        "disputable": money(answer.get("disputable_amount")) or 0.0, "unverified": money(answer.get("unverified_amount")) or 0.0,
        "rows": rows, "letter_type": letter["letter_type"],
        "bill_inconsistencies": [answer.get("inconsistency") or "documents inconsistent"]
        if answer.get("documents_inconsistent") is True else [],
    }
    out["route"] = "llm_only"
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


# --------------------------------------------------------------------------- metrics and report


def false_disputes(answer: dict, result: dict) -> tuple[int, int]:
    """(rows the answer file calls matches_policy, of those called does_not_match_policy)."""
    a = result.get("audit")
    if not a:
        return 0, 0
    exp = C0.expected_rows(answer)
    correct = [k for k, v in exp.items() if v == "matches_policy" and k in a["rows"]]
    return len(correct), sum(1 for k in correct if a["rows"][k]["verdict"] == "does_not_match_policy")


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "-"


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(0.95 * len(xs)) - 1))] if xs else 0.0


def metrics(results: list[dict], model: str | None) -> dict:
    sc = [r["score"] for r in results]
    rows = sum(s.get("rows", 0) for s in sc)
    rows_right = sum(s.get("rows_right", 0) for s in sc)
    errors = [abs(float(s["disputable_expected"]) - float(s["disputable_engine"])) for s in sc if "disputable_engine" in s]
    fd_rows = [r["false_dispute"] for r in results]
    fd_cases = [r for r in results if r["score"].get("expected_overall") == "matches_policy"]
    tin = sum(r["result"].get("llm", {}).get("input_tokens", 0) for r in results)
    tout = sum(r["result"].get("llm", {}).get("output_tokens", 0) for r in results)
    price = PRICES.get(model or "")
    secs = [r["result"].get("seconds", 0.0) for r in results if r["result"].get("seconds") is not None]
    bad = [r for r in results if r["result"]["route"] in ("crashed", "unreadable_llm_answer", "tool_error")]
    return {
        "cases": len(results),
        "overall_right": sum(1 for s in sc if s.get("overall_right")),
        "rows": rows, "rows_right": rows_right,
        "rupee_cases": len(errors), "rupee_within_1": sum(1 for e in errors if e < 1),
        "rupee_mae": round(statistics.mean(errors), 2) if errors else None,
        "rupee_median": round(statistics.median(errors), 2) if errors else None,
        "false_dispute_rows": sum(f[1] for f in fd_rows), "correct_rows": sum(f[0] for f in fd_rows),
        "false_dispute_cases": sum(1 for r in fd_cases if r["score"].get("engine_overall") == "disputable"),
        "matches_cases": len(fd_cases),
        "input_tokens": tin, "output_tokens": tout,
        "cost_usd": round((tin * price[0] + tout * price[1]) / 1e6, 4) if price else None,
        "median_seconds": round(statistics.median(secs), 2) if secs else None,
        "p95_seconds": round(p95(secs), 2) if secs else None,
        "errors": len(bad), "error_cases": [r["case"] for r in bad],
    }


def report(mode: str, runs: list[dict], model: str | None, split: str) -> str:
    label = {"on": "Signature 1 ON: engine + matcher", "off": "Signature 1 OFF: LLM-only baseline"}[mode]
    lines = [f"# {label}", "",
             f"Split `{split}`, {runs[0]['metrics']['cases']} cases, {len(runs)} run(s), "
             f"{datetime.now():%d %b %Y %H:%M}. Model (OFF only): `{model or '-'}`.", "",
             "| Run | Overall verdict right | Row verdicts right | Disputable within ₹1 | Rupee error (mean / median) "
             "| False disputes (rows) | False disputes (cases) | Tokens in / out | Cost (USD) | Latency median / p95 (s) | Errors |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, run in enumerate(runs, 1):
        m = run["metrics"]
        lines.append(f"| {i} | {pct(m['overall_right'], m['cases'])} | {pct(m['rows_right'], m['rows'])} | "
                     f"{pct(m['rupee_within_1'], m['rupee_cases'])} | {m['rupee_mae']} / {m['rupee_median']} | "
                     f"{pct(m['false_dispute_rows'], m['correct_rows'])} | {pct(m['false_dispute_cases'], m['matches_cases'])} | "
                     f"{m['input_tokens']:,} / {m['output_tokens']:,} | {m['cost_usd'] if m['cost_usd'] is not None else '-'} | "
                     f"{m['median_seconds']} / {m['p95_seconds']} | {m['errors']} |")
    lines += ["", "False disputes (rows): answer file `matches_policy`, run `does_not_match_policy`. "
              "False disputes (cases): answer file overall `matches_policy`, run `disputable`. "
              "Cost is the LLM's only (the engine and matcher are code); ON makes no LLM call.", "",
              "## Every case (last run)", "",
              "| Case | Route | Expected | Got | Rows | Disputable (expected / got) | Row misses |", "|---|---|---|---|---|---|---|"]
    for r in runs[-1]["cases"]:
        s = r["score"]
        miss = ", ".join(f"{k} {v['expected']}→{v['engine']}" for k, v in (s.get("row_misses") or {}).items())
        rows = f"{s['rows_right']}/{s['rows']}" if "rows" in s else "-"
        mark = "✓" if s.get("overall_right") else "✗"
        lines.append(f"| {r['case']} | {r['result']['route']} | {s.get('expected_overall')} | {s.get('engine_overall')} {mark} | "
                     f"{rows} | {s.get('disputable_expected', '-')} / {s.get('disputable_engine', '-')} | {miss} |")
    return "\n".join(lines) + "\n"


def append_history(mode: str, split: str, model: str | None, m: dict, stamp: str) -> None:
    path = RESULTS / "history.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "signature1", "split", "model", "cases", "overall_right", "rows_right", "rows",
                        "rupee_within_1", "rupee_cases", "rupee_mae", "false_dispute_rows", "correct_rows",
                        "false_dispute_cases", "matches_cases", "cost_usd", "median_s", "p95_s", "errors"])
        w.writerow([stamp, mode, split, model or "", m["cases"], m["overall_right"], m["rows_right"], m["rows"],
                    m["rupee_within_1"], m["rupee_cases"], m["rupee_mae"], m["false_dispute_rows"], m["correct_rows"],
                    m["false_dispute_cases"], m["matches_cases"], m["cost_usd"], m["median_seconds"], m["p95_seconds"],
                    m["errors"]])


# --------------------------------------------------------------------------- main


async def run_once(mode: str, names: list[str], answers: dict, mapping: dict, extracted: dict, http: bool,
                   llm) -> list[dict]:
    results = []
    async with ClaimClearToolkit(mode="http" if http else None) as tk:
        for name in names:
            case_id = C0.store_case_id(name, answers[name], mapping)
            ex = extracted.get(name, {"error": "not extracted"})
            t0 = time.perf_counter()
            try:
                res = await (C0.run_case(tk, case_id, ex) if mode == "on" else run_case_llm_only(tk, case_id, ex, llm))
            except Exception as exc:                      # recorded in the report, never hidden
                res = {"route": "crashed", "steps": {}, "error": f"{type(exc).__name__}: {exc}"[:500]}
            res.setdefault("seconds", round(time.perf_counter() - t0, 2))
            results.append({"case": name, "source": answers[name]["source"], "result": res,
                            "score": C0.score(answers[name], res), "false_dispute": false_disputes(answers[name], res)})
            print(f"  {mode:<3} {name:<18} {res['route']:<22} {results[-1]['score'].get('engine_overall')}", flush=True)
    return results


def run_config(mode: str, stamp: str, args, model: str | None, names: list[str]) -> dict:
    """Everything needed to repeat the run with the same configuration (saved in the run's JSON)."""
    import hashlib
    import platform
    import subprocess

    def git(*cmd: str) -> str:
        try:
            return subprocess.run(["git", *cmd], cwd=C0.REPO, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""
    tools = ["get_policy_wording", "get_policy", "get_claim_history"]
    tools += (["list_case_documents", "get_document_text", "expected_settlement", "reproduce_deduction",
               "audit_settlement_letter", "clauses_for_rule"] if mode == "on" else ["search_clauses"])
    return {
        "run_id": f"signature1_{mode}_{stamp}", "signature1": mode, "split": args.split, "cases": len(names),
        "case_ids": names, "repeat": args.repeat, "transport": "http" if args.http else "stdio",
        "git_commit": git("rev-parse", "--short", "HEAD") or "unknown", "git_dirty": bool(git("status", "--porcelain")),
        "python": platform.python_version(), "tools": tools,
        "llm": None if mode == "on" else {
            "model": model, "temperature": 0, "max_tokens": 4000, "response_format": "json_object", "calls_per_case": 1,
            "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:16],
            "clauses": {"k_per_query": 3, "queries": "each letter row (particulars + reason), the rejection reason, "
                                                      "and " + ", ".join(STANDARD_QUERIES)}},
        "engine": None if mode == "off" else {"match_tolerance_inr": 1, "hypotheses": "engine/hypotheses.py (51)"},
    }


async def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--signature1", choices=("on", "off", "both"), default=os.environ.get("CLAIMCLEAR_SIGNATURE1", "on"),
                   help="on = engine + matcher (default), off = LLM-only baseline, both = one after the other "
                        "(env CLAIMCLEAR_SIGNATURE1)")
    p.add_argument("--repeat", type=int, default=1, help="run the whole set N times (the brief asks for 3)")
    p.add_argument("--split", default="dev", choices=("dev", "heldout"),
                   help="dataset split under development/dev_data/dataset/ (default dev)")
    p.add_argument("--only", nargs="*", help="dataset case IDs to run")
    p.add_argument("--model", help="OFF only: override the model (default CLAIMCLEAR_CHAT_MODEL or openai/gpt-4.1-mini)")
    p.add_argument("--http", action="store_true", help="use the servers started by scripts/dev_servers.py")
    p.add_argument("--no-write", action="store_true", help="print the report, don't write results/")
    args = p.parse_args(argv)

    load_dotenv(C0.REPO / ".env")
    C0.SPLIT = args.split
    C0.WORK = C0.REPO / "var" / "signature1" / args.split
    C0.WORK.mkdir(parents=True, exist_ok=True)
    mapping, extracted = C0.prepare()
    answers = {a.stem: json.loads(a.read_text(encoding="utf-8"))
               for a in sorted((C0.DATASET / args.split / "answers").glob("*.json"))}
    names = [n for n in answers if not args.only or n in args.only]
    modes = ("on", "off") if args.signature1 == "both" else (args.signature1,)
    for mode in modes:
        llm = llm_from_env(args.model) if mode == "off" else None
        base = getattr(llm, "bound", llm)
        model = (getattr(base, "model_name", None) or getattr(base, "model", None)) if llm else None
        runs = []
        for i in range(args.repeat):
            print(f"Signature 1 {mode.upper()}, run {i + 1}/{args.repeat}, {len(names)} cases", flush=True)
            cases = await run_once(mode, names, answers, mapping, extracted, args.http, llm)
            runs.append({"cases": cases, "metrics": metrics(cases, model)})
        text = report(mode, runs, model, args.split)
        if args.no_write:
            print(text)
            continue
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        config = run_config(mode, stamp, args, model, names)
        text = text.replace("\n\n", f"\n\nRun ID `{config['run_id']}` · commit `{config['git_commit']}`"
                                    f"{' (uncommitted changes)' if config['git_dirty'] else ''}.\n\n", 1)
        (RESULTS / f"signature1_{mode}_{stamp}.md").write_text(text, encoding="utf-8")
        (RESULTS / f"signature1_{mode}_{stamp}.json").write_text(
            json.dumps({"signature1": mode, "split": args.split, "model": model, "config": config, "runs": runs},
                       indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        for run in runs:
            append_history(mode, args.split, model, run["metrics"], stamp)
        print(f"wrote {RESULTS / f'signature1_{mode}_{stamp}.md'} and .json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
