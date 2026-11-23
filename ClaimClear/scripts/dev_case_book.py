"""The dev case book: every development case, what it contains, what the policy says should be paid, and how
ClaimClear handles it. Generated from the dataset and the evaluation results, so nothing is typed by hand.

    python scripts/dev_case_book.py      # writes docs/member2_knowledge_memory_tools/dev_dataset_case_book.md
    python scripts/dev_case_book.py --html out.html         # also an HTML version (for a PDF)

Reads ``development/dev_data/dataset/dev`` (``cases.json``, ``answers/``, ``reference/policies.json``, ``reference/claim_history.json``)
and the latest whole-application results ``development/dev_eval/dev_cases/results/dev_cases.json`` (the fixed workflow, C0) and
``development/dev_eval/graph_dev_cases/results/graph_dev_cases.json`` (the multi-agent graph). Re-run the evaluations first if the
code changed. Personal details on the synthetic documents (names, dates of birth) are left out.

Standard library only.
"""
# (Project restructuring #1)

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEV = REPO / "development"/"dev_data" / "dataset" / "dev"
REVIEWED_UIN = "GODHLIP24179V022324"
VERDICT = {"matches_policy": "Matches the policy", "disputable": "May be disputable",
           "does_not_match_policy": "Does not match the policy", "not_verifiable": "Can't be checked yet",
           "inconsistent_documents": "Inconsistent documents", "method_matches": "Right method, insurer's base",
           None: "No audit"}
ROLE = {"bill": "hospital bill", "settlement_letter": "settlement letter", "policy_schedule": "policy schedule",
        "policy_wording": "policy wording", "discharge_summary": "discharge summary", "other_bills": "other bills",
        "earlier_settlement_1": "earlier settlement letter", "earlier_settlement_2": "second earlier settlement letter"}

# Why a case differs from its answer key, in plain language (kept in step with dataset_guide.md, section 10.1).
_PROPORTIONATE = ("ClaimClear follows IRDAI's 2020 circular for the proportionate deduction: medicines, consumables, "
                  "implants, tests and ICU charges are never cut, and only a room above its limit triggers the cut. The "
                  "answer key follows the case's older printed wording, which spares only medicines. This is a recorded "
                  "team decision (`development/dev_eval/dev_cases/decisions.json`, `proportionate-2020`); it still counts as a miss.")
DIFFERS = {
    "gen-dev-50b4e6": _PROPORTIONATE + " Here it changes the overall verdict: ClaimClear finds ₹2,794.66 that may be "
                                       "disputable where the answer key says the letter matches the policy.",
    "gen-dev-6a82b1": _PROPORTIONATE + " Both say \"may be disputable\"; only the amounts differ.",
    "gen-dev-a0a2f1": _PROPORTIONATE + " Both say \"may be disputable\"; only the amounts differ.",
    "syn-dev-021": ("The receipt has no admission or discharge date, so the engine can't check the 60-day "
                    "post-hospitalisation window and asks for the admission date instead of guessing. The dev run has "
                    "nobody to answer, so the case ends as \"can't be checked yet\"; with an answer it is decided."),
    "gen-dev-0fa297": ("The overall verdict is right. Three rows wait as \"can't be checked\" because the bill has blood "
                       "plasma, and the rules don't say whether blood products may be cut when the room is above its "
                       "limit: the engine asks how the hospital prices them, and the dev run has nobody to answer."),
}


def inr(v) -> str:
    if v is None or v == "":
        return "-"
    v = float(v)
    whole, _, paise = f"{abs(v):.2f}".partition(".")
    if len(whole) > 3:
        head, tail, groups = whole[:-3], whole[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + groups + [tail])
    return f"{'-' if v < 0 else ''}₹{whole}" + ("" if paise == "00" else f".{paise}")


def load() -> dict:
    cases = json.loads((DEV / "cases.json").read_text(encoding="utf-8"))["cases"]
    policies = json.loads((DEV / "reference" / "policies.json").read_text(encoding="utf-8"))
    history = json.loads((DEV / "reference" / "claim_history.json").read_text(encoding="utf-8"))
    answers = {c["case_id"]: json.loads((DEV / "answers" / f"{c['case_id']}.json").read_text(encoding="utf-8"))
               for c in cases}
    c0 = {r["case"]: r for r in _json(REPO / "development"/"dev_eval" / "dev_cases" / "results" / "dev_cases.json")}
    graph = {r["case"]: r for r in _json(REPO / "development"/"dev_eval" / "graph_dev_cases" / "results" / "graph_dev_cases.json")}
    return {"cases": cases, "policies": policies, "history": history, "answers": answers, "c0": c0, "graph": graph}


def _json(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


# --------------------------------------------------------------------------- one case, as data


def title_of(answer: dict) -> str:
    sc = answer.get("scenario") or {}
    if sc.get("title"):
        return sc["title"]
    err = (sc.get("insurer_error") or {}).get("kind", "")
    return (sc.get("summary") or err.replace("_", " ") or sc.get("type", "")).strip()


def scenario_lines(answer: dict) -> list[str]:
    sc = answer.get("scenario") or {}
    out = []
    if sc.get("type"):
        out.append(f"Type: {sc['type'].replace('_', ' ')}" + (f" ({sc['recipe']})" if sc.get("recipe") else ""))
    if sc.get("what_changed"):
        out.append(f"What was changed: {sc['what_changed']}")
    if sc.get("attack_goal") and not sc["attack_goal"].lower().startswith("none"):
        out.append(f"Aim of the change: {sc['attack_goal']}")
    err = sc.get("insurer_error") or {}
    if err:
        detail = ", ".join(f"{k} {v}" for k, v in err.items() if k != "kind")
        out.append(f"The insurer's error built into the letter: {err.get('kind', '').replace('_', ' ')}"
                   + (f" ({detail})" if detail else ""))
    if sc.get("summary"):
        out.append(f"Story: {sc['summary']}")
    if sc.get("expected_flags"):
        out.append("Signals a careful reader should notice: " + ", ".join(f.replace("_", " ") for f in sc["expected_flags"]))
    return out


def wording_line(case: dict, c0: dict) -> str:
    w = ((c0.get("result") or {}).get("steps") or {}).get("wording") or {}
    if case["wording_uin"] == REVIEWED_UIN:
        return (f"Go Digit Arogya Sanjeevani (UIN {REVIEWED_UIN}), the reviewed wording: limits from "
                "development/dev_data/wordings/rules, clauses cited from the reviewed rule map")
    return (f"The case's own wording (UIN {case['wording_uin']}, a policy_wording.pdf in the case) is not in the reviewed "
            f"catalogue, so ClaimClear checks against the reviewed Go Digit wording ({w.get('wording_uin', REVIEWED_UIN)}) "
            "and says so; the user is asked to upload their wording for exact clause citations")


def expected_handling(answer: dict) -> list[str]:
    exp = answer.get("expected") or {}
    v = exp.get("overall_verdict")
    rej = exp.get("rejection")
    sc = answer.get("scenario") or {}
    out = []
    if rej:
        out.append(f"The claim was rejected ({(rej.get('kind') or '').replace('_', ' ')}); the right verdict on the rejection "
                   f"is \"{VERDICT.get(rej.get('expected_verdict'), rej.get('expected_verdict'))}\".")
    if v == "disputable":
        bad = [d["particulars"] for d in exp.get("deductions") or [] if d.get("verdict") == "does_not_match_policy"]
        amt = exp.get("disputable_amount", exp.get("gap"))
        out.append(f"Explain every deduction, then offer a grievance for {inr(amt)} covering only: " + "; ".join(bad)
                   + ". File it only after the policyholder approves the exact text.")
    elif v == "matches_policy":
        out.append("Explain every deduction against its clause; nothing to dispute, so no grievance is offered.")
    elif v == "not_verifiable":
        out.append("Say plainly what can't be checked and why, and suggest asking the insurer for its working or item "
                   "list. No grievance on what can't be shown.")
    elif v == "inconsistent_documents":
        out.append("Point out that the documents disagree with each other (e.g. a charge billed twice and paid twice) "
                   "and suggest confirming with the hospital or insurer before calling anything an overpayment.")
    if sc.get("type") in ("poisoned", "malicious", "adversarial"):
        out.append("Treat hidden text, annotations and look-alike characters as untrusted: use only what a person can "
                   "see, and flag the rest.")
    if sc.get("type") == "formats":
        out.append("Read the document despite its format (scan, photo or handwriting): OCR where needed, and ask for a "
                   "better copy rather than guess if a page can't be read.")
    if sc.get("type") == "synthetic_fake":
        out.append("Notice the bill's own inconsistencies; they support the insurer's rejection. Never accuse.")
    return out


def system_result(case_id: str, data: dict) -> dict:
    r, g = data["c0"].get(case_id) or {}, data["graph"].get(case_id) or {}
    sc, res = r.get("score") or {}, r.get("result") or {}
    audit = res.get("audit") or {}
    flags = ((res.get("steps") or {}).get("documents") or {}).get("security_flags") or {}
    questions = ((res.get("steps") or {}).get("settlement") or {}).get("questions") or []
    return {"route": res.get("route"), "graph_outcome": g.get("outcome"),
            "engine": sc.get("engine_overall"), "right": sc.get("overall_right"),
            "rows": f"{sc.get('rows_right', 0)}/{sc.get('rows', 0)}" if sc.get("rows") else "-",
            "payable": audit.get("policy_payable"), "paid": audit.get("insurer_paid"),
            "disputable": audit.get("disputable"), "unverified": audit.get("unverified"),
            "grievance_rows": res.get("grievance_rows") or [], "questions": questions, "flags": sorted(flags),
            "methods": {k: (v.get("method"), v.get("verdict")) for k, v in (audit.get("rows") or {}).items()}}


def build(data: dict) -> list[dict]:
    out = []
    for case in data["cases"]:
        cid = case["case_id"]
        a = data["answers"][cid]
        exp = a.get("expected") or {}
        # As case-records picks them: a case's own record when several cases reuse one policy number
        same = [p for p in data["policies"] if p["policy_no"] == case["policy_no"]]
        pol = next((p for p in same if p.get("case_id") == cid), next((p for p in same if not p.get("case_id")), {}))
        hist = [h for h in data["history"] if h["policy_no"] == case["policy_no"] and h.get("case_id") in (None, "", cid)]
        out.append({
            "id": cid, "source": case["source"], "title": title_of(a), "scenario": scenario_lines(a),
            "documents": [ROLE.get(Path(d["file"]).stem, ROLE.get(d["role"], d["role"].replace("_", " ")))
                          for d in case["documents"]],
            "policy": {"no": case["policy_no"], "insurer": pol.get("insurer"), "product": pol.get("product"),
                       "si": pol.get("sum_insured"), "period": f"{pol.get('period_start')} to {pol.get('period_end')}",
                       "inception": pol.get("first_inception")},
            "wording": wording_line(case, data["c0"].get(cid) or {}),
            "history": [{"claim": h["claim_id"], "admission": h.get("admission"), "diagnosis": h.get("diagnosis"),
                         "status": h.get("status"), "settled": h.get("settled_amount")} for h in hist],
            "expected": {"verdict": exp.get("overall_verdict"), "payable": exp.get("policy_payable"),
                         "paid": exp.get("insurer_paid"), "gap": exp.get("gap"),
                         "disputable": exp.get("disputable_amount", exp.get("gap") if exp.get("overall_verdict") == "disputable" else 0),
                         "unverified": exp.get("unverified_amount"), "notes": exp.get("notes"),
                         "deductions": exp.get("deductions") or [], "rejection": exp.get("rejection")},
            "handling": expected_handling(a), "system": system_result(cid, data)})
    return out


# --------------------------------------------------------------------------- rendering

INTRO = """The 42 development cases ClaimClear is built and scored on (`development/dev_data/dataset/dev`). For each case: what it
contains, which policy wording applies, the claim history, what the insurer paid, what the policy says should be paid,
every deduction with its expected verdict and the reason, how ClaimClear should handle it, and what ClaimClear actually
did in the latest whole-application run. Generated by `scripts/dev_case_book.py` from the dataset's own files; re-run it
after the evaluations. See `docs/member2_knowledge_memory_tools/dataset_guide.md` for the format itself.

* **Two sources.** 22 *synthetic* cases (`syn-dev-*`) built around the reviewed Go Digit Arogya Sanjeevani wording,
  many of them stress tests (hidden text, scans, photos, handwriting, altered or fake bills). 20 *generated* cases
  (`gen-dev-*`) built from a second insurer's wording, each with one planted insurer error and a worked solution.
* **Amounts.** "Policy should pay" is the answer key's payable amount under the wording; "May be disputable" is what the
  insurer paid short of it that a specific deduction explains, after co-pay; "Can't be checked" is what no known
  calculation reproduces.
* **What ClaimClear did** is the fixed workflow (C0) and the multi-agent graph over all five MCP servers, with the
  development stand-in extraction (no LLM). The graph and C0 give the same verdict on every case."""


def md(cases: list[dict]) -> str:
    n_right = sum(1 for c in cases if c["system"]["right"])
    lines = ["# Development dataset: the case book", "", INTRO, "",
             f"**Overall verdict right on {n_right} of {len(cases)} cases** in the latest run. Why the others differ, "
             "in plain language: [dataset guide, section 10.1](dataset_guide.md#101-why-some-dev-cases-are-not-identified-correctly).", "",
             "## All cases at a glance", "",
             "| Case | What it tests | Insurer paid | Policy should pay | Expected verdict | ClaimClear |",
             "|---|---|---|---|---|---|"]
    for c in cases:
        e, s = c["expected"], c["system"]
        mark = "✓" if s["right"] else "✗"
        lines.append(f"| [{c['id']}](#{c['id']}) | {c['title'][:70]} | {inr(e['paid'])} | {inr(e['payable'])} | "
                     f"{VERDICT.get(e['verdict'], e['verdict'])} | {VERDICT.get(s['engine'], s['engine'])} {mark} |")
    by_type = Counter((c["scenario"][0] if c["scenario"] else "Type: -").replace("Type: ", "").split(" (")[0] for c in cases)
    lines += ["", "Case types: " + ", ".join(f"{k} {v}" for k, v in by_type.most_common()) + ".", ""]
    for c in cases:
        lines += case_md(c)
    return "\n".join(lines) + "\n"


def case_md(c: dict) -> list[str]:
    e, s, p = c["expected"], c["system"], c["policy"]
    out = ["---", "", f"## {c['id']}", "", f"**{c['title']}** ({c['source']})", ""]
    out += [f"* {line}" for line in c["scenario"]] + [""]
    out += ["| | |", "|---|---|",
            f"| Documents | {', '.join(c['documents'])} |",
            f"| Policy | {p['no']} · {p['insurer']} · {p['product']} · sum insured {inr(p['si'])} · {p['period']} · "
            f"first taken {p['inception']} |",
            f"| Wording followed | {c['wording']} |",
            "| Claim history | " + ("; ".join(f"{h['claim']} admitted {h['admission']} ({h['diagnosis']}), {h['status']}, "
                                         f"{inr(h['settled'])} paid" for h in c["history"]) or "none on record") + " |",
            f"| Insurer paid | {inr(e['paid'])} |",
            f"| Policy should pay | {inr(e['payable'])} |",
            f"| Gap · may be disputable · can't be checked | {inr(e['gap'])} · {inr(e['disputable'])} · {inr(e['unverified'])} |",
            f"| Expected verdict | {VERDICT.get(e['verdict'], e['verdict'])} |", ""]
    if e["deductions"]:
        out += ["| Deduction on the letter | Insurer | Policy-correct | Expected | Why |", "|---|---|---|---|---|"]
        for d in e["deductions"]:
            out.append(f"| {d.get('particulars', '').replace('|', '/')} | {inr(d.get('amount'))} | {inr(d.get('correct_amount'))} | "
                       f"{VERDICT.get(d.get('verdict'), d.get('verdict'))} | {(d.get('why') or '').replace('|', '/')} |")
        out.append("")
    if e["rejection"]:
        out += [f"**Rejection** ({(e['rejection'].get('kind') or '').replace('_', ' ')}): {e['rejection'].get('reason')}", ""]
    if e["notes"]:
        out += [f"*Answer-key note:* {e['notes']}", ""]
    out += ["**How ClaimClear should handle it**", ""] + [f"* {h}" for h in c["handling"]] + [""]
    out += ["**What ClaimClear did**", "",
            f"* Verdict: {VERDICT.get(s['engine'], s['engine'])} {'✓' if s['right'] else '✗'} · rows right {s['rows']} · "
            f"route `{s['route']}` · graph outcome `{s['graph_outcome']}`",
            f"* Policy payable {inr(s['payable'])} · insurer paid {inr(s['paid'])} · may be disputable {inr(s['disputable'])} · "
            f"can't be checked {inr(s['unverified'])}"]
    if s["grievance_rows"]:
        out.append(f"* Grievance offered for rows {', '.join(s['grievance_rows'])} (never filed without approval)")
    if s["questions"]:
        out.append(f"* Asked: {', '.join(s['questions'])}")
    if c["id"] in DIFFERS:
        out.append(f"* **Why it differs from the answer key:** {DIFFERS[c['id']]}")
    if s["flags"]:
        out.append(f"* Guardrail flags: {'; '.join(s['flags'])}")
    methods = [f"{k}: {m}" for k, (m, v) in s["methods"].items() if m]
    if methods:
        out.append(f"* Methods found: {'; '.join(methods)}")
    return out + [""]


def to_html(markdown: str) -> str:
    """A small Markdown subset (headings, tables, bullets, bold, italic, code, links, rules) to HTML."""
    import re
    out, table, in_list = [], [], False

    def inline(t: str) -> str:
        t = html.escape(t, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", t)
        t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
        t = re.sub(r"\[(.+?)\]\((#[^)]+)\)", r'<a href="\2">\1</a>', t)
        # a link to another document can't be followed from the PDF: show its name and path instead
        return re.sub(r"\[(.+?)\]\(([^)#]+)(?:#[^)]*)?\)", r"\1 (<code>docs/member2_knowledge_memory_tools/\2</code>)", t)

    def flush_table():
        if table:
            rows = [r for r in table if not re.match(r"^\|[-| ]+\|$", r)]
            cells = [[x.strip() for x in r.strip("|").split("|")] for r in rows]
            head = all(x == "" for x in cells[0])
            body = cells[1:] if head else cells
            h = "" if head else ""
            out.append('<table>' + ("" if head else "<tr>" + "".join(f"<th>{inline(x)}</th>" for x in cells[0]) + "</tr>")
                       + "".join("<tr>" + "".join(f"<td>{inline(x)}</td>" for x in r) + "</tr>"
                                 for r in (body if head else cells[1:])) + "</table>")
            table.clear()

    for line in markdown.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("## "):
            anchor = line[3:].strip()
            out.append(f'<h2 id="{html.escape(anchor)}">{inline(anchor)}</h2>')
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.strip() == "---":
            out.append('<hr>')
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    css = """@page{size:A4;margin:15mm 13mm;@bottom-center{content:"ClaimClear · Development dataset case book · page " counter(page);font:8pt "Segoe UI",Arial;color:#777}}
body{font-family:"Segoe UI",Calibri,Arial,sans-serif;font-size:9.3pt;line-height:1.42;color:#1b2430}
h1{color:#0f5e7a;border-bottom:2.5px solid #0f5e7a;font-size:20pt}h2{color:#0f5e7a;font-size:13pt;margin:4px 0;page-break-after:avoid}
hr{border:0;border-top:1px solid #d5dbe3;margin:14px 0 6px;page-break-after:avoid}
table{border-collapse:collapse;width:100%;margin:5px 0 9px;font-size:8.4pt}tr{page-break-inside:avoid}
th{background:#0f5e7a;color:#fff;text-align:left;padding:4px 5px}td{border-bottom:1px solid #d5dbe3;padding:3px 5px;vertical-align:top}
td:first-child{width:24%;color:#41505f}code{font-family:Consolas,monospace;font-size:8pt;background:#eef2f6;padding:0 3px}
ul{margin:3px 0 7px;padding-left:18px}li{margin:1px 0}a{color:#0f5e7a;text-decoration:none}p{margin:4px 0 6px}"""
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Development dataset case book</title><style>{css}</style>"
            f"</head><body>{''.join(out)}</body></html>")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "docs" / "member2_knowledge_memory_tools" / "dev_dataset_case_book.md"))
    ap.add_argument("--html", help="also write an HTML version here")
    args = ap.parse_args(argv)
    text = md(build(load()))
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    if args.html:
        Path(args.html).write_text(to_html(text), encoding="utf-8")
        print(f"wrote {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
