"""Track UI judge eval runs over time. Reads a finished run's results.json; no model calls.

1. ``eval_history.csv`` (next to this file, in git): one line per run, so the whole team sees the trend on GitHub.
2. LangSmith, when ``LANGSMITH_API_KEY`` is set (ClaimClear/.env): the run becomes an experiment on the dataset
   ``claimclear-ui-judge`` with per-case scores (verdict, payable, paid, security, judge), so runs can be compared
   case by case. Without the key this step is skipped. Accounts outside the US region also need the region's
   address, e.g. ``LANGSMITH_ENDPOINT=https://apac.api.smith.langchain.com`` (otherwise every call is 403 Forbidden).

    ui_judge_eval.py ... --track [--langsmith]                      # track the run (LangSmith only when asked)
    ../.venv-agents/Scripts/python eval_track.py ../var/eval/ui_judge/<time> [--label negatives]   # an earlier run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "eval_history.csv"
DATASET = "claimclear-ui-judge"
COLUMNS = ["date", "commit", "model", "label", "cases", "errors", "judge_pass", "judge_partial", "judge_fail",
           "verdict_ok", "payable_ok", "paid_ok", "security_ok", "minutes", "run", "langsmith"]
SECURITY = ("attack_flagged", "negative_left_alone", "control_left_alone")   # control_ = older runs' name


def scores(r: dict) -> dict[str, Optional[float]]:
    """One case's scores, 1/0 (None when the case has no such check). An error scores 0 everywhere."""
    c, j = r.get("checks") or {}, r.get("judge") or {}
    if r.get("error") or (r.get("got") or {}).get("error") or not c:
        return {"ran": 0, "verdict_ok": 0, "payable_ok": 0, "paid_ok": 0, "security_ok": None, "judge": 0}
    sec = next((c[k] for k in SECURITY if k in c), None)
    return {"ran": 1, "verdict_ok": int(c["verdict_ok"]), "payable_ok": int(c["payable_ok"]), "paid_ok": int(c["paid_ok"]),
            "security_ok": None if sec is None else int(sec),
            "judge": {"pass": 1, "partial": 0.5, "fail": 0}.get(j.get("verdict"))}


def summary(results: dict) -> dict:
    s = [scores(r) for r in results.values()]
    count = lambda key: sum(1 for x in s if x[key] == 1)                          # noqa: E731
    with_sec = [x for x in s if x["security_ok"] is not None]
    verdicts = [(r.get("judge") or {}).get("verdict") for r in results.values()]
    return {"cases": len(s), "errors": sum(1 for x in s if not x["ran"]),
            "judge_pass": verdicts.count("pass"), "judge_partial": verdicts.count("partial"),
            "judge_fail": verdicts.count("fail"), "verdict_ok": count("verdict_ok"), "payable_ok": count("payable_ok"),
            "paid_ok": count("paid_ok"), "security_ok": f"{count('security_ok')}/{len(with_sec)}" if with_sec else "",
            "minutes": round(sum(r.get("seconds") or 0 for r in results.values()) / 60, 1)}


def tags_of(r: dict) -> list[str]:
    return list((r.get("expected") or {}).get("tags") or [])


def by_tag(results: dict) -> dict[str, dict]:
    """Per tag: cases, judge pass / partial / fail, verdict right, payable right, errors."""
    out: dict[str, dict] = {}
    for r in results.values():
        s, j = scores(r), (r.get("judge") or {}).get("verdict")
        for t in tags_of(r) or ["untagged"]:
            d = out.setdefault(t, {"cases": 0, "pass": 0, "partial": 0, "fail": 0, "verdict_ok": 0, "payable_ok": 0, "errors": 0})
            d["cases"] += 1
            if j in ("pass", "partial", "fail"):
                d[j] += 1
            d["verdict_ok"] += s["verdict_ok"] == 1
            d["payable_ok"] += s["payable_ok"] == 1
            d["errors"] += not s["ran"]
    return dict(sorted(out.items(), key=lambda kv: (-kv[1]["cases"], kv[0])))


def by_tag_table(results: dict) -> str:
    lines = ["| Tag | Cases | Judge pass / partial / fail | Verdict right | Payable right | Errors |", "|---|---|---|---|---|---|"]
    lines += [f"| {t} | {d['cases']} | {d['pass']} / {d['partial']} / {d['fail']} | {d['verdict_ok']} | {d['payable_ok']} | "
              f"{d['errors']} |" for t, d in by_tag(results).items()]
    return "\n".join(lines)


def commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except OSError:
        return ""


def append_history(run: Path, results: dict, label: str, model: str, langsmith_url: str = "") -> dict:
    row = {"date": time.strftime("%Y-%m-%d %H:%M"), "commit": commit(), "model": model, "label": label,
           **summary(results), "run": run.name, "langsmith": langsmith_url}
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def to_langsmith(results: dict, label: str, model: str) -> str:
    """The run as a LangSmith experiment; returns its URL ('' when LANGSMITH_API_KEY is not set)."""
    if not os.environ.get("LANGSMITH_API_KEY"):
        return ""
    from langsmith import Client, evaluate

    client = Client()
    ds = client.read_dataset(dataset_name=DATASET) if client.has_dataset(dataset_name=DATASET) else \
        client.create_dataset(DATASET, description="ClaimClear test cases graded by ui_judge_eval.py (UI path + LLM judge)")
    expected = lambda r: {k: (r.get("expected") or {}).get(k) for k in              # noqa: E731
                          ("kind", "group", "verdict", "payable", "paid", "disputable", "behaviour")}
    meta = lambda r: {"tags": tags_of(r), "kind": (r.get("expected") or {}).get("kind"),   # noqa: E731
                      "source": (r.get("expected") or {}).get("source")}
    have = {e.inputs.get("case_id"): e for e in client.list_examples(dataset_id=ds.id)}
    new = [{"inputs": {"case_id": cid}, "outputs": expected(r), "metadata": meta(r)}
           for cid, r in results.items() if cid not in have]
    if new:
        client.create_examples(dataset_id=ds.id, examples=new)
    for cid, r in results.items():                      # tags added later reach cases already in the dataset
        if cid in have and (have[cid].metadata or {}).get("tags") != meta(r)["tags"]:
            client.update_example(have[cid].id, metadata={**(have[cid].metadata or {}), **meta(r)})
    if new or any(cid in have for cid in results):
        have = {e.inputs.get("case_id"): e for e in client.list_examples(dataset_id=ds.id)}

    def recorded(inputs: dict) -> dict:                 # the "target": this run's recorded outcome, no model call
        r = results[inputs["case_id"]]
        g, j = r.get("got") or {}, r.get("judge") or {}
        return {"verdict": (r.get("checks") or {}).get("verdict"), "policy_payable": g.get("policy_payable"),
                "insurer_paid": g.get("insurer_paid"), "security_flags": g.get("security_flags"),
                "judge": j.get("verdict"), "judge_summary": j.get("summary"), "problems": j.get("problems"),
                "error": r.get("error") or g.get("error"), "seconds": r.get("seconds"), "tags": tags_of(r)}

    def graded(inputs: dict) -> dict:
        return {"results": [{"key": k, "score": v} for k, v in scores(results[inputs["case_id"]]).items() if v is not None]}

    out = evaluate(recorded, data=[have[cid] for cid in results], evaluators=[graded], client=client,
                   experiment_prefix=f"ui-judge-{label}", metadata={"bundle": label, "commit": commit(), "model": model}, max_concurrency=4)
    try:
        return out._manager._experiment.url or ""          # noqa: SLF001  (no public accessor in 0.15)
    except AttributeError:
        return out.experiment_name


def track(run: Path, label: str, model: str, langsmith: bool = False) -> dict:
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    url = ""
    try:
        url = to_langsmith(results, label, model) if langsmith else ""
    except Exception as exc:                            # tracking must never lose the run: history.csv still gets the line
        print(f"LangSmith: not sent ({type(exc).__name__}: {exc})")
    row = append_history(run, results, label, model, url)
    print(f"tracked: {HISTORY.name} +1 line" + (f"; LangSmith: {url}" if url else
                                                 " (LangSmith: not requested; add --langsmith)" if not langsmith else
                                                 "; LangSmith: not sent" if os.environ.get("LANGSMITH_API_KEY") else
                                                 " (LangSmith off: no LANGSMITH_API_KEY)"))
    return row


def main() -> None:
    import app as chat_app                               # ClaimClear/.env (LANGSMITH_* keys), same rule as the chat
    from claimclear_graph import chat
    chat_app.load_dotenv()
    ap = argparse.ArgumentParser(description="Track a finished UI judge eval run")
    ap.add_argument("run", type=Path, help="the run folder (var/eval/ui_judge/<time>)")
    ap.add_argument("--label", default="manual", help="which cases: negatives, attacks, team-dev, ...")
    ap.add_argument("--langsmith", action="store_true", help="also send the run to LangSmith (uses quota)")
    ap.add_argument("--model", default=os.environ.get("CLAIMCLEAR_CHAT_MODEL") or chat.OPENROUTER_DEFAULT_MODEL,
                    help="the model the run used")
    a = ap.parse_args()
    track(a.run, a.label, a.model, langsmith=a.langsmith)


if __name__ == "__main__":
    main()
