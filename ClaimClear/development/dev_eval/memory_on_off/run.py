"""Memory on vs off: run the development cases with and without ClaimClear's long-term memory.

    .venv/Scripts/python.exe development/dev_eval/memory_on_off/run.py                       # all dev letters, 4 conditions  # Project restructuring #1
    .venv/Scripts/python.exe development/dev_eval/memory_on_off/run.py --pipeline my_graph:run   # Member 3's graph instead  # Project restructuring #1

What it does, per condition:

1. Takes every development case of ``development/dev_data/dataset/dev`` that has a settlement letter and the  (# Project restructuring #1)
   extracted bill and letter fields the engine needs (the synthetic cases; gen-data cases carry
   only PDFs, so they need the document reader first). The held-out split is never read. Cases are
   grouped by policyholder (one user per policy) and each user's sessions run in admission order,
   as the same person coming back.
2. Builds the ``case`` argument the agents would build (claim, policy, history) and runs the
   pipeline on it: by default the settlement-engine's ``audit_settlement_letter`` tool, in process.
3. **Memory on**: before a session, the user's remembered claims are merged into the history
   (``merge_history``); after a final audit, the policy and claim are remembered.
   **Memory off**: nothing is remembered.
4. Scores every audit against the dataset's hand-checked answer key: verdict per letter row,
   disputable rupees, questions asked, failures.

It runs two history settings: ``reference`` (the insurer's claim history from case-records is
available, as in development) and ``none`` (no insurer history: what ClaimClear knows comes only
from the documents and, with memory on, from earlier sessions; this is the realistic case, since
ClaimClear has no access to an insurer's records).

Results go to ``development/dev_eval/memory_on_off/results/memory_on_off_<date>.md`` and ``.json``.  (# Project restructuring #1)

A pipeline is ``async def run(case: dict, letter: dict, memory_context: dict) -> dict`` returning a
``LetterAuditOut``-shaped dict (``rows``, ``disputable_amount``, ``questions``, ``settlement``).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import importlib
import json
import statistics
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

REPO = Path(__file__).resolve().parents[3]          # the ClaimClear folder (development/dev_eval/memory_on_off/run.py)
for sub in ("servers/settlement_engine", "memory"):
    sys.path.insert(0, str(REPO / sub))

from claimclear_memory import MemoryStore, MemoryStoreError, merge_history  # noqa: E402
from engine.dataset import answer_key, default_dataset_dir, load_case, load_letter  # noqa: E402
from engine.identifiers import canonical_policy_no, same_policy  # noqa: E402
from mcp_server.convert import case_payload, letter_payload  # noqa: E402

Pipeline = Callable[[dict, dict, dict], Awaitable[dict]]
OUT_DIR = Path(__file__).resolve().parent / "results"


# --------------------------------------------------------------------------- sessions


def dev_sessions(dataset_dir: Path) -> list[dict]:
    """Development cases with a settlement letter, ordered per user by admission date."""
    out = []
    for path in sorted((dataset_dir / "dev" / "answers").glob("*.json")):
        answer = json.loads(path.read_text(encoding="utf-8"))
        c = {"case": answer["case_id"]}
        if answer.get("source") != "claimclear-synthetic":
            continue
        letter_id = answer["documents"].get("settlement_letter.pdf")
        if not letter_id:
            continue
        try:
            case = load_case(letter_id, dataset_dir)
        except (KeyError, ValueError) as exc:            # e.g. a letter on an invented policy
            out.append({"case": c["case"], "letter_id": letter_id, "load_error": f"{type(exc).__name__}: {exc}"})
            continue
        policy_key = canonical_policy_no(case.policy.policy_no)
        out.append({"case": c["case"], "letter_id": letter_id, "policy_no": case.policy.policy_no,
                    "user_id": "u_" + hashlib.sha256(policy_key.encode()).hexdigest()[:12],
                    "admission": case.claim.admission.isoformat() if case.claim.admission else "9999-12-31"})
    return sorted(out, key=lambda s: (s.get("user_id", ""), s.get("admission", ""), s["case"]))


# --------------------------------------------------------------------------- pipelines


def engine_pipeline() -> tuple[Pipeline, Callable[[], Any]]:
    """The settlement-engine's audit_settlement_letter tool, in process (what the critic calls)."""
    from mcp import Client
    from mcp_server import create_server

    client = Client(create_server())
    started = {"ctx": None}

    async def run(case: dict, letter: dict, memory_context: dict) -> dict:
        if started["ctx"] is None:
            started["ctx"] = await client.__aenter__()
        res = await started["ctx"].call_tool("audit_settlement_letter", {"case": case, "letter": letter})
        if res.is_error:
            return {"error": res.content[0].text}
        return res.structured_content

    async def close():
        if started["ctx"] is not None:
            await client.__aexit__(None, None, None)

    return run, close


def load_pipeline(spec: str) -> tuple[Pipeline, Callable[[], Any]]:
    module, _, name = spec.partition(":")
    fn = getattr(importlib.import_module(module), name or "run")

    async def close():
        return None
    return fn, close


# --------------------------------------------------------------------------- scoring


def _dec(value) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def score(audit: dict, key: dict) -> dict:
    """Compare one audit with the answer key."""
    if "error" in audit:
        return {"failed": True, "error": audit["error"][:200]}
    expected = [d.get("expected_verdict") for d in (key.get("insurer_deductions") or [])]
    got = [r.get("verdict") for r in audit.get("rows", []) if r.get("row_id", "").startswith("R")]
    correct = sum(1 for e, g in zip(expected, got) if e == g)
    exp_disp, got_disp = _dec(key.get("disputable_amount")), _dec(audit.get("disputable_amount"))
    return {"failed": False, "rows": len(expected), "rows_correct": correct,
            "disputable": None if got_disp is None else str(got_disp),
            "disputable_expected": None if exp_disp is None else str(exp_disp),
            "disputable_error": None if (exp_disp is None or got_disp is None) else str(abs(got_disp - exp_disp)),
            "questions": len(audit.get("questions") or []),
            "status": (audit.get("settlement") or {}).get("status")}


# --------------------------------------------------------------------------- one condition


async def run_condition(sessions: list[dict], pipeline: Pipeline, memory_on: bool, server_history: str,
                        dataset_dir: Path, workdir: Path) -> list[dict]:
    store = MemoryStore(workdir / f"memory_{int(memory_on)}_{server_history}.db")
    results = []
    consented: set[str] = set()
    for s in sessions:
        row = {"case": s["case"], "letter_id": s["letter_id"], "user_id": s.get("user_id")}
        if "load_error" in s:
            results.append({**row, "failed": True, "error": s["load_error"]})
            continue
        case = case_payload(load_case(s["letter_id"], dataset_dir))
        letter = letter_payload(load_letter(s["letter_id"], dataset_dir))
        if same_policy(case["claim"]["policy_no"], case["policy"]["policy_no"]):
            case["claim"]["policy_no"] = case["policy"]["policy_no"]     # agents pass get_policy's number
        if server_history == "none":
            case["history"] = []
        memory_context: dict = {}
        remembered = 0
        mem = None
        if memory_on:
            if s["user_id"] not in consented:
                store.for_user(s["user_id"]).grant_consent("memory_on_off_experiment")
                consented.add(s["user_id"])
            mem = store.session_memory(s["user_id"])
            earlier = mem.claim_history(case["policy"]["policy_no"])
            remembered = len(earlier)
            case["history"] = merge_history(case["history"], earlier)
            memory_context = mem.context(policy_no=case["policy"]["policy_no"])
        audit = await pipeline(case, letter, memory_context)
        result = {**row, **score(audit, answer_key(s["letter_id"], dataset_dir)), "remembered_claims": remembered,
                  "history_used": len(case["history"])}
        if mem is not None and "error" not in audit:
            try:
                mem.remember_policy(case["policy"])
                mem.remember_claim(case, audit, case_id=s["case"], letter=letter)
                result["stored"] = True
            except MemoryStoreError as exc:
                result["stored"] = False
                result["not_stored"] = exc.code
        results.append(result)
    return results


def summarise(results: list[dict]) -> dict:
    ok = [r for r in results if not r.get("failed")]
    errors = [Decimal(r["disputable_error"]) for r in ok if r.get("disputable_error") is not None]
    rows = sum(r["rows"] for r in ok)
    correct = sum(r["rows_correct"] for r in ok)
    return {"letters": len(results), "failed": len(results) - len(ok), "rows": rows, "rows_correct": correct,
            "verdict_accuracy": round(correct / rows, 3) if rows else None,
            "disputable_exact": sum(1 for e in errors if e <= Decimal("1")),
            "disputable_scored": len(errors),
            "median_disputable_error": str(statistics.median(errors)) if errors else None,
            "max_disputable_error": str(max(errors)) if errors else None,
            "questions": sum(r["questions"] for r in ok),
            "letters_using_memory": sum(1 for r in ok if r.get("remembered_claims")),
            "stored": sum(1 for r in ok if r.get("stored"))}


# --------------------------------------------------------------------------- report


CONDITIONS = [("reference", False), ("reference", True), ("none", False), ("none", True)]


def report(all_results: dict, sessions: list[dict], pipeline_name: str) -> str:
    lines = [f"# Memory on vs off ({dt.date.today().isoformat()})", "",
             f"Pipeline: `{pipeline_name}`. Development cases with a settlement letter: {len(sessions)}, "
             f"{len({s.get('user_id') for s in sessions if s.get('user_id')})} policyholders. Scored against the "
             "dataset's hand-checked answer key. Held-out cases are not used.", "",
             "| Insurer history | Memory | Letters | Failed | Verdicts right | Disputable within ₹1 | Median / max disputable error | Questions asked | Letters that used memory | Claims stored |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for (hist, on), results in all_results.items():
        s = summarise(results)
        acc = f"{s['rows_correct']}/{s['rows']} ({s['verdict_accuracy']:.1%})" if s["rows"] else "-"
        lines.append(f"| {hist} | {'on' if on else 'off'} | {s['letters']} | {s['failed']} | {acc} | "
                     f"{s['disputable_exact']}/{s['disputable_scored']} | {s['median_disputable_error']} / "
                     f"{s['max_disputable_error']} | {s['questions']} | {s['letters_using_memory']} | {s['stored']} |")
    lines += ["", "## Letters whose result changes with memory", ""]
    changed = []
    for hist in ("reference", "none"):
        off = {r["letter_id"]: r for r in all_results[(hist, False)]}
        for r in all_results[(hist, True)]:
            o = off[r["letter_id"]]
            keys = ("rows_correct", "disputable", "questions", "status")
            if any(r.get(k) != o.get(k) for k in keys):
                changed.append(f"| {hist} | {r['case']} | {r['letter_id']} | "
                               + " | ".join(f"{o.get(k)} -> {r.get(k)}" for k in keys) + " |")
    if changed:
        lines += ["| Insurer history | Case | Letter | Verdicts right | Disputable | Questions | Status |",
                  "|---|---|---|---|---|---|---|", *changed]
    else:
        lines.append("None.")
    lines += ["", "## Failures", ""]
    fails = {(r["letter_id"], r.get("error", "")) for res in all_results.values() for r in res if r.get("failed")}
    lines += [f"* {lid}: {err}" for lid, err in sorted(fails)] or ["None."]
    return "\n".join(lines) + "\n"


async def main_async(args) -> int:
    dataset_dir = Path(args.dataset) if args.dataset else default_dataset_dir()
    sessions = dev_sessions(dataset_dir)
    if args.limit:
        sessions = sessions[: args.limit]
    pipeline, close = (load_pipeline(args.pipeline) if args.pipeline else engine_pipeline())
    all_results = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for hist, on in CONDITIONS:
                all_results[(hist, on)] = await run_condition(sessions, pipeline, on, hist, dataset_dir, Path(tmp))
    finally:
        await close()
    text = report(all_results, sessions, args.pipeline or "settlement-engine audit_settlement_letter")
    print(text)
    if not args.no_write:
        out = Path(args.out) if args.out else OUT_DIR
        out.mkdir(parents=True, exist_ok=True)
        stem = out / f"memory_on_off_{dt.date.today().isoformat()}"
        stem.with_suffix(".md").write_text(text, encoding="utf-8")
        stem.with_suffix(".json").write_text(json.dumps(
            {f"{h}|{'on' if o else 'off'}": {"summary": summarise(r), "letters": r} for (h, o), r in all_results.items()},
            indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {stem}.md and .json")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Memory on vs off on the development cases.")
    p.add_argument("--pipeline", help="module:function of an async pipeline (default: the settlement-engine tool)")
    p.add_argument("--dataset", help="development/dev_data/dataset (default)  (# Project restructuring #1)")
    p.add_argument("--limit", type=int, help="only the first N sessions (smoke test)")
    p.add_argument("--out", help="results folder (default development/dev_eval/memory_on_off/results)  (# Project restructuring #1)")
    p.add_argument("--no-write", action="store_true", help="print only")
    sys.stdout.reconfigure(encoding="utf-8")
    return asyncio.run(main_async(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
