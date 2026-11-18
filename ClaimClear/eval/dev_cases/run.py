"""Whole-application run over the development cases: every case through every server, scored.

    .venv-agents/Scripts/python.exe eval/dev_cases/run.py              # all dev cases, servers over stdio
    .venv-agents/Scripts/python.exe eval/dev_cases/run.py --http       # against scripts/dev_servers.py
    .venv-agents/Scripts/python.exe eval/dev_cases/run.py --only gen-dev-147e01

Run in the **agents'** environment: it drives the servers through ``claimclear_tools`` exactly as
Member 3's graph does (the C0 fixed workflow, no LLM). Per case:

1. **Upload** (the app's step): the dev split is registered into ``var/dev_cases/case_store``.
2. **Document reader**: ``list_case_documents`` and ``get_document_text`` for every document; the
   guardrail signals (unreadable pages, hidden or untrusted content).
3. **Policy analyst**: ``get_policy``, ``get_policy_wording`` (ask the user for their wording?),
   ``get_claim_history``.
4. **Extraction**: the claim and the letter. DEV STAND-IN for the document reader's LLM extraction
   (``extract.py``: the synthetic cases' printed fields, gen-data's PDFs parsed).
5. **Settlement auditor**: ``expected_settlement``, ``reproduce_deduction`` for every letter row
   (and COPAY / REJECTION).
6. **Explainer and critic**: ``clauses_for_rule`` for every row's rule (policy-kb, in the case's
   wording), ``audit_settlement_letter``, the critic's figure check on a draft.
7. **Score** against the case's answer file (read only here, after the run): overall verdict, each
   row's verdict, the policy-correct payable and the disputable amount.

Writes ``eval/dev_cases/results/dev_cases.md`` and ``.json``. Held-out cases are never read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from claimclear_tools import ClaimClearToolkit, build_case, signals
from claimclear_tools.config import find_repo, server_python
from claimclear_tools.critic import allowed_figures, unsupported_figures, wording_for
from claimclear_tools.results import ClaimClearToolError

REPO = find_repo()
DATASET = REPO / "data" / "dataset"
WORK = REPO / "var" / "dev_cases"
RESULTS = Path(__file__).resolve().parent / "results"
SPLIT = "dev"


def prepare() -> tuple[dict, dict]:
    """Register the dev split into a fresh store and extract every case's claim and letter."""
    store = WORK / "case_store"
    if store.exists():
        import shutil
        shutil.rmtree(store)
    py = server_python(REPO)
    subprocess.run([py, "-m", "case_records.register_dataset", "--split", SPLIT, "--store", str(store)],
                   cwd=REPO / "servers" / "case_records", check=True, capture_output=True)
    extracted = WORK / f"extracted_{SPLIT}.json"
    subprocess.run([py, str(Path(__file__).resolve().parent / "extract.py"), SPLIT, str(extracted)],
                   cwd=REPO, check=True, capture_output=True)
    os.environ["CLAIMCLEAR_CASE_STORE"] = str(store)
    os.environ["CLAIMCLEAR_REFERENCE_DIR"] = str(DATASET / SPLIT / "reference")
    return (json.loads((WORK / "dataset_map.json").read_text(encoding="utf-8")),
            json.loads(extracted.read_text(encoding="utf-8")))


def lookalike(printed: str, real: str) -> bool:
    """The same policy number once look-alike characters (Cyrillic А, Ѕ, ...) are mapped: a spoofed print.

    Uses the settlement engine's own table (``engine/identifiers.py``, standard library only)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "engine_identifiers", REPO / "servers" / "settlement_engine" / "engine" / "identifiers.py")
    ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ids)
    return printed != real and ids.same_policy(printed, real) and ids.has_lookalikes(printed)


def store_case_id(name: str, answer: dict, mapping: dict) -> str:
    """DEV STAND-IN for the app, which hands the graph its case ID."""
    first = next(iter(answer["documents"]))
    key = answer["documents"][first] if answer["source"] == "claimclear-synthetic" else f"{name}/{first}"
    return mapping[key]["case_id"]


# --------------------------------------------------------------------------- one case


async def run_case(tk: ClaimClearToolkit, case_id: str, extracted: dict) -> dict:
    out: dict = {"steps": {}, "route": None}
    t0 = time.perf_counter()

    # 2. document reader
    docs = await tk.list_case_documents(case_id)
    pages = unreadable = 0
    flags: Counter = Counter()
    for d in docs["documents"]:
        text = await tk.get_document_text(case_id, d["document_id"])
        pages += len(text["pages"])
        unreadable += len(signals.unreadable_pages(text))
        flags.update(signals.security_flags(text))
    out["steps"]["documents"] = {"count": len(docs["documents"]), "pages": pages, "unreadable_pages": unreadable,
                                 "roles": sorted(d["role"] for d in docs["documents"]),
                                 "security_flags": dict(flags)}

    # 3. policy analyst
    wording = await tk.get_policy_wording(case_id)
    out["steps"]["wording"] = {k: wording[k] for k in ("status", "wording_uin", "schedule_wording_uin", "wording_needed")}
    try:
        policy = await tk.get_policy(case_id)
        history = await tk.get_claim_history(case_id)
    except ClaimClearToolError as exc:
        out["steps"]["policy"] = {"error": exc.info.code}
        out["route"] = "ask_user_for_policy"         # the graph would ask the user to confirm the schedule
        out["seconds"] = round(time.perf_counter() - t0, 2)
        return out
    out["steps"]["policy"] = {"policy_no": policy["policy_no"], "sum_insured": policy["sum_insured"],
                              "earlier_claims": len(history)}

    # 4. extraction (stand-in)
    if "error" in extracted or "letter" not in extracted:
        out["route"] = "extraction_failed"
        out["steps"]["extraction"] = extracted.get("error", "no letter")
        return out
    letter = extracted["letter"]
    claim = extracted["claim"]
    if claim["policy_no"] != policy["policy_no"] and lookalike(claim["policy_no"], policy["policy_no"]):
        # the bill prints the policy number with look-alike characters (a parser attack): the graph uses the
        # schedule's number from get_policy and raises a guardrail flag
        claim = {**claim, "policy_no": policy["policy_no"]}
        out["steps"]["documents"]["security_flags"]["lookalike_policy_number_on_bill"] = 1
    try:
        case = build_case(claim, policy, history)
    except ValueError as exc:
        out["route"] = "policy_mismatch"
        out["steps"]["extraction"] = str(exc)
        return out
    out["steps"]["extraction"] = {"how": extracted["extraction"], "lines": len(extracted["claim"]["lines"]),
                                  "letter_rows": len(letter["rows"]), "letter_type": letter["letter_type"]}

    # 5. settlement auditor
    try:
        settlement = await tk.expected_settlement(case)
        rows = {}
        for row_id in signals.rows_to_audit(letter):
            rows[row_id] = await tk.reproduce_deduction(case, letter, row_id)
        audit = await tk.audit_settlement_letter(case, letter)
    except ClaimClearToolError as exc:
        # INVALID_ARGUMENTS: the extracted claim is impossible (e.g. discharge before admission); the graph
        # would send it back to the document reader or ask the user to correct the dates
        out["route"] = "invalid_extraction" if exc.info.code == "INVALID_ARGUMENTS" else "tool_error"
        out["steps"]["audit"] = {"error": exc.info.code, "message": exc.info.message[:300]}
        return out
    # Questions the letter's audit still needs: the engine settles some from the letter itself (a rejection the bill
    # confirms, a claim the insurer paid with no waiting-period row), and then the settlement's own question is moot.
    questions = signals.questions_to_ask(None if audit.get("policy_payable") is not None else settlement, rows.values())
    out["steps"]["settlement"] = {"status": settlement["status"], "payable": settlement["payable_amount"],
                                  "questions": [q["question_id"] for q in questions],
                                  "warnings": settlement["warnings"]}

    # 6. explainer and critic
    cited = missing = 0
    for r in rows.values():
        if not r.get("rule_ref"):
            continue
        found = await tk.clauses_for_rule(r["rule_ref"], wording_uin=policy["wording_uin"])
        if found.get("clauses"):
            cited += 1
        else:
            missing += 1
    draft = " ".join(f"{r['particulars']}: ₹{r['insurer_amount']:,} {wording_for(r)}." for r in rows.values())
    if audit.get("disputable_amount") is not None:
        draft += f" May be disputable: ₹{audit['disputable_amount']:,}."
    problems = unsupported_figures(draft, allowed_figures(settlement, rows.values(), audit))
    out["steps"]["explain"] = {"rules_cited": cited, "rules_without_clause": missing,
                               "critic_unsupported_figures": [str(p) for p in problems]}
    out["audit"] = {
        "policy_payable": audit["policy_payable"], "insurer_paid": audit["insurer_paid"],
        "disputable": audit["disputable_amount"], "unverified": audit["unverified_amount"],
        "rows": {k: {"verdict": v["verdict"], "insurer_amount": v["insurer_amount"],
                     "policy_amount": v["policy_amount"], "particulars": v["particulars"], "kind": v["kind"],
                     "kind_source": v["kind_source"], "method": v["method"], "explanation": v["explanation"][:300],
                     "questions": [q["question_id"] for q in v["questions"]]} for k, v in rows.items()},
        "letter_type": letter["letter_type"],
        "bill_inconsistencies": [d["description"] for d in signals.bill_inconsistencies(audit)],
        "warnings": audit["warnings"],
    }
    out["route"] = "ask_user" if questions else signals.after_letter_audit(audit)
    out["grievance_rows"] = [r["row_id"] for r in signals.disputable_rows(rows.values())]
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


# --------------------------------------------------------------------------- scoring


def engine_overall(result: dict) -> str | None:
    a = result.get("audit")
    if not a:
        return None
    rows = a["rows"]
    if "REJECTION" in rows:
        v = rows["REJECTION"]["verdict"]
        return {"does_not_match_policy": "disputable"}.get(v, v)
    if a.get("bill_inconsistencies"):
        return "inconsistent_documents"
    if (a["disputable"] or 0) >= 1:
        return "disputable"
    if (a["unverified"] or 0) >= 1 or any(r["verdict"] == "not_verifiable" for r in rows.values()):
        return "not_verifiable"
    return "matches_policy"


def expected_rows(answer: dict) -> dict[str, str]:
    """Letter row ID -> expected verdict (co-payment rows are the audit's COPAY row)."""
    exp = (answer.get("expected") or {}).get("deductions") or []
    out, n = {}, 0
    for d in exp:
        if "co-pay" in d["particulars"].lower() or "copay" in d["particulars"].lower():
            out["COPAY"] = d["verdict"]
        else:
            n += 1
            out[f"R{n}"] = d["verdict"]
    return out


def score(answer: dict, result: dict) -> dict:
    exp = answer.get("expected") or {}
    got_overall = engine_overall(result)
    s = {"expected_overall": exp.get("overall_verdict"), "engine_overall": got_overall,
         "overall_right": got_overall == exp.get("overall_verdict")}
    a = result.get("audit")
    if not a:
        return s
    rows = expected_rows(answer)
    compared = {k: (v, a["rows"][k]["verdict"]) for k, v in rows.items() if k in a["rows"]}
    s["rows"] = len(compared)
    s["rows_right"] = sum(1 for e, g in compared.values() if e == g)
    s["row_misses"] = {k: {"expected": e, "engine": g} for k, (e, g) in compared.items() if e != g}
    # for a rejection the engine's payable is what the policy would pay if the claim were covered: not comparable
    if exp.get("policy_payable") is not None and a["policy_payable"] is not None and a["letter_type"] != "rejection":
        s["payable_expected"], s["payable_engine"] = exp["policy_payable"], a["policy_payable"]
        s["payable_right"] = abs(float(exp["policy_payable"]) - float(a["policy_payable"])) < 1
    want = exp.get("disputable_amount", exp.get("gap") if exp.get("overall_verdict") == "disputable" else 0)
    if want is not None and a["disputable"] is not None:
        s["disputable_expected"], s["disputable_engine"] = want, a["disputable"]
        s["disputable_right"] = abs(float(want) - float(a["disputable"])) < 1
    return s


# --------------------------------------------------------------------------- report


def decided_disagreements() -> dict[str, str]:
    """Case ID -> decision ID, for the cases where ClaimClear decided against the answer key (decisions.json)."""
    path = Path(__file__).resolve().parent / "decisions.json"
    if not path.exists():
        return {}
    return {case: d["id"] for d in json.loads(path.read_text(encoding="utf-8"))["decisions"] for case in d["cases"]}


def report(results: list[dict]) -> str:
    decided = decided_disagreements()
    def rate(items, key):
        have = [r["score"][key] for r in items if key in r["score"]]
        return f"{sum(have)}/{len(have)}" if have else "-"

    lines = ["# Whole-application run: development cases", "",
             "Every dev case of `data/dataset/dev` through the toolkit and all five servers (no LLM: the claim and "
             "letter extraction is the development stand-in in `extract.py`). Scored against each case's answer file.",
             "", "| Source | Cases | Ran to the end | Overall verdict right | Row verdicts right | Payable right (±₹1) "
             "| Disputable right (±₹1) |", "|---|---|---|---|---|---|---|"]
    for src, label in (("claimclear-synthetic", "synthetic"), ("gen-data", "gen-data"), (None, "all")):
        items = [r for r in results if src is None or r["source"] == src]
        ran = sum(1 for r in items if "audit" in r["result"])
        rows_have = [r["score"] for r in items if "rows" in r["score"]]
        rows = f"{sum(s['rows_right'] for s in rows_have)}/{sum(s['rows'] for s in rows_have)}" if rows_have else "-"
        lines.append(f"| {label} | {len(items)} | {ran} | {rate(items, 'overall_right')} | {rows} | "
                     f"{rate(items, 'payable_right')} | {rate(items, 'disputable_right')} |")
    routes = Counter(r["result"]["route"] for r in results)
    wording = Counter(r["result"]["steps"]["wording"]["status"] for r in results)
    flagged = [r["case"] for r in results if r["result"]["steps"]["documents"]["security_flags"]]
    lines += ["", f"Routes: {dict(routes)}. Wording: {dict(wording)}. Cases with guardrail flags: {len(flagged)}.", "",
              "## Every case", "",
              "| Case | Route | Expected | Engine | Rows | Payable (expected / engine) | Disputable (expected / engine) | Notes |",
              "|---|---|---|---|---|---|---|---|"]
    for r in results:
        s, res = r["score"], r["result"]
        notes = []
        if s.get("row_misses"):
            notes.append("rows: " + ", ".join(f"{k} {v['expected']}→{v['engine']}" for k, v in s["row_misses"].items()))
        if res["steps"].get("policy", {}).get("error"):
            notes.append(f"get_policy {res['steps']['policy']['error']}")
        if res["steps"].get("audit", {}).get("error"):
            notes.append(f"{res['steps']['audit']['error']}: {res['steps']['audit']['message'][:120]}")
        q = res["steps"].get("settlement", {}).get("questions")
        if q:
            notes.append("asks " + ", ".join(q))
        if res["steps"]["wording"]["wording_needed"]:
            notes.append("wording not reviewed")
        if r["case"] in decided:
            notes.append(f"answer key differs by decision `{decided[r['case']]}` (decisions.json)")
        rows = f"{s['rows_right']}/{s['rows']}" if "rows" in s else "-"
        pay = f"{s.get('payable_expected', '-')} / {s.get('payable_engine', '-')}"
        dis = f"{s.get('disputable_expected', '-')} / {s.get('disputable_engine', '-')}"
        mark = "✓" if s.get("overall_right") else "✗"
        lines.append(f"| {r['case']} | {res['route']} | {s.get('expected_overall')} | {s.get('engine_overall')} {mark} | "
                     f"{rows} | {pay} | {dis} | {'; '.join(notes)} |")
    if decided:
        lines += ["", f"{len(decided)} cases are where ClaimClear decided against the answer key "
                  f"({', '.join(sorted(decided))}; see `decisions.json`). They still count as misses above."]
    lines += ["", "gen-data cases use another insurer's Arogya Sanjeevani wording, which ClaimClear hasn't reviewed: "
              "they are checked against the standard limits, and `get_policy_wording` asks for the user's wording."]
    return "\n".join(lines) + "\n"


async def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--http", action="store_true", help="use the servers started by scripts/dev_servers.py")
    p.add_argument("--only", nargs="*", help="dataset case IDs to run")
    p.add_argument("--no-write", action="store_true", help="print the report, don't write results/")
    args = p.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    mapping, extracted = prepare()
    answers = {a.stem: json.loads(a.read_text(encoding="utf-8")) for a in sorted((DATASET / SPLIT / "answers").glob("*.json"))}
    names = [n for n in answers if not args.only or n in args.only]
    results = []
    async with ClaimClearToolkit(mode="http" if args.http else None) as tk:
        for name in names:
            case_id = store_case_id(name, answers[name], mapping)
            try:
                res = await run_case(tk, case_id, extracted.get(name, {"error": "not extracted"}))
            except Exception as exc:                      # recorded in the report, never hidden
                res = {"route": "crashed", "steps": {"documents": {"security_flags": {}},
                                                     "wording": {"status": "?", "wording_needed": False}},
                       "error": f"{type(exc).__name__}: {exc}"}
            results.append({"case": name, "source": answers[name]["source"], "result": res,
                            "score": score(answers[name], res)})
            print(f"{name:<18} {res['route']:<20} {results[-1]['score'].get('engine_overall')}")
    text = report(results)
    if args.no_write:
        print(text)
    else:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "dev_cases.md").write_text(text, encoding="utf-8")
        (RESULTS / "dev_cases.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str),
                                                encoding="utf-8")
        print(f"wrote {RESULTS / 'dev_cases.md'} and .json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
