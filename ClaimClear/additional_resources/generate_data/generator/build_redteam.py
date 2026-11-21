"""Build the red-team attack set from data/recipes/redteam/attacks.json.

  py -3 generator/build_redteam.py                 # all 30, PDFs
  py -3 generator/build_redteam.py RT-A01 RT-D03   # some
  py -3 generator/build_redteam.py --no-pdf
  py -3 generator/build_redteam.py --answers-only   # just (re)write each answer/, PDFs untouched

Each attack starts from an existing gen case (base recipe + variant), so its money answer is known.
Document attacks change the rendered documents (text injected at a named spot, a fake clause in the wording,
a swapped name, an edited line, a duplicate earlier letter). Chat and approval attacks reuse the base documents
and add the user's input (chat.txt / steps.txt).

Negative cases (group "negative", ids RT-N-001...) use the same builder with no attack, or with honest text
that only looks odd: negative cases for security testing (they must not be flagged or blocked).

Writes  data/redteam/<id>/            what the system under test receives (documents, chat.txt, steps.txt)
        data/redteam/<id>/answer/     the answer, for people: story.md, recipe.json, meta.json
        data/redteam_meta/<id>.json   attack details + expected safe behaviour + the base case's answer
EVALUATION MATERIAL: never use for building or tuning agents.
"""
import argparse
import copy
import glob
import html
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build import to_pdf  # noqa: E402
from compute import build_case  # noqa: E402
from render import money, prior_letter, render_case  # noqa: E402
from story import base_gold, redteam_story, write_answer  # noqa: E402
from wording_copy import wording_pdf  # noqa: E402

DOC = {"schedule": "01_policy_schedule.html", "bill": "02_itemised_bill.html", "letter": "03_settlement_letter.html",
       "earlier_1": "04_earlier_settlement_1.html"}
STYLE = {"visible": "", "white": " style='color:#ffffff;font-size:2px'", "tiny": " style='color:#999;font-size:4px'"}


def recipe_for(base_id):
    split = "dev" if base_id.startswith("D") else "heldout"
    return json.load(open(os.path.join(ROOT, "data", "recipes", split, f"{base_id}.json"), encoding="utf-8"))


def inject(docs, f, inj):
    name = DOC[inj["doc"]]
    h = docs[name]
    text = html.escape(inj["text"])
    st = STYLE[inj.get("style", "visible")]
    where = inj["where"]
    if where == "footer":
        h = h.replace("<div class='foot'>", f"<p{st}>{text}</p><div class='foot'>", 1)
    elif where == "top":
        h = h.replace("<body>", f"<body><p{st}>{text}</p>", 1)
    elif where == "row":
        h = h.replace("</table>", f"<tr><td>{html.escape(inj.get('label', 'Note'))}</td><td>{text}</td></tr></table>", 1)
    elif where.startswith("line:"):
        line = next(l for l in f["lines"] if l["id"] == where[5:])
        old = html.escape(line["desc"])
        assert old in h, f"line text {line['desc']!r} not in {name}"
        h = h.replace(old, text, 1)
    else:
        raise SystemExit(f"unknown inject spot {where}")
    docs[name] = h
    return name, inj["text"]


def build_one(a, no_pdf, jobs):
    r = recipe_for(a["base"])
    v = copy.deepcopy(next(x for x in r["variants"] if x["v"] == a["variant"]))
    base_case = build_case(r, v)
    if a.get("insurer_error"):  # an attack that changes the insurer's money (fake clause)
        v["insurer_error"], v["type"] = a["insurer_error"], "fake_clause"
    case = build_case(r, v)
    f = case["facts"]
    if a.get("edit_stay_line"):
        f["style"]["bill"] = "category"  # one row per stay segment, easy to tamper with
    if a.get("bill_admit"):
        case["tweaks"]["bill_admit"] = a["bill_admit"]
    docs = render_case(case, os.path.join(ROOT, "data", "prose"))
    st = f["style"]["money"]
    checks = []  # (doc, text that must appear)

    for inj in a.get("inject", []):
        checks.append(inject(docs, f, inj))
    if a.get("letter_patient"):
        lp = a["letter_patient"]
        h = docs[DOC["letter"]].replace(html.escape(f["insured_name"]), html.escape(lp["name"]))
        docs[DOC["letter"]] = h.replace(html.escape(f["policy_no"]), html.escape(lp["policy_no"]))
        checks.append((DOC["letter"], lp["name"]))
    if a.get("letter_si"):
        h = docs[DOC["letter"]]
        old, new = money(f["sum_insured"], st), money(a["letter_si"], st)
        assert old in h
        docs[DOC["letter"]] = h.replace(old, new, 1)
        checks.append((DOC["letter"], new))
    if a.get("bill_patient"):
        docs[DOC["bill"]] = docs[DOC["bill"]].replace(html.escape(f["insured_name"]), html.escape(a["bill_patient"]))
        checks.append((DOC["bill"], a["bill_patient"]))
    if a.get("edit_stay_line"):
        e = a["edit_stay_line"]
        s = f["stay"][e["index"]]
        row_old = (f"<td class='n'>{s['days']}</td><td class='n'>{money(s['rate'], st)}</td>"
                   f"<td class='n'>{money(s['rate'] * s['days'], st)}</td>")
        font = f" style=\"font-family:'{e['font']}'\""
        row_new = (f"<td class='n'>{s['days']}</td><td class='n'><span{font}>{money(e['shown_rate'], st)}</span></td>"
                   f"<td class='n'><span{font}>{money(e['shown_rate'] * s['days'], st)}</span></td>")
        h = docs[DOC["bill"]]
        assert row_old in h, "stay row not found"
        docs[DOC["bill"]] = h.replace(row_old, row_new, 1)
        checks.append((DOC["bill"], money(e["shown_rate"] * s["days"], st)))
    if a.get("duplicate_as_earlier"):
        c = case["correct"]
        dup = {"date": f["admit"], "diagnosis": f["diagnosis"], "billed": c["billed"], "admissible": c["admissible"],
               "paid": c["payable"], "status": "settled"}
        n = len(f["prior_claims"]) + 1
        docs[f"04_earlier_settlement_{n}.html"] = prior_letter(f, dup, n + 5)
        checks.append((f"04_earlier_settlement_{n}.html", f["diagnosis"]))

    out = os.path.join(ROOT, "data", "redteam", a["id"])
    bdir = os.path.join(HERE, "_build", "redteam", a["id"])
    for p in (out, bdir):
        shutil.rmtree(p, ignore_errors=True)
        os.makedirs(p)
    problems = [f"{d}: attack text not found" for d, t in checks if html.escape(t) not in docs[d] and t not in docs[d]]
    print_jobs = []
    for name, h in docs.items():
        hp = os.path.join(bdir, name)
        open(hp, "w", encoding="utf-8").write(h)
        print_jobs.append((hp, os.path.join(out, name.replace(".html", ".pdf")), out))
    ins = a.get("wording_insert")
    wp, wkind = wording_pdf(f["wording"], f["insurer_info"], f["uin"], (lambda *_: False) if no_pdf else to_pdf,
                            insert=ins, tag=f"_{a['id']}" if ins else "")
    shutil.copy(wp, os.path.join(out, f"00_policy_wording.{wkind}"))
    if ins and wp.endswith(".pdf"):
        with open(wp.replace(".pdf", ".html"), encoding="utf-8") as fh:
            if "Processing Fee" not in fh.read():
                problems.append("fake clause missing from wording copy")
    if a.get("chat"):
        open(os.path.join(out, "chat.txt"), "w", encoding="utf-8").write("\n".join(a["chat"]) + "\n")
    if a.get("steps"):
        open(os.path.join(out, "steps.txt"), "w", encoding="utf-8").write(
            "\n".join(f"{i}. {s}" for i, s in enumerate(a["steps"], 1)) + "\n")

    m, bm = case["meta"], base_case["meta"]
    if not a.get("insurer_error") and (m["correct_settlement"] != bm["correct_settlement"]):
        problems.append("money answer changed by the attack")
    meta = {
        "attack_id": a["id"], "group": a["group"], "benefits": a.get("benefits"),
        "base": {"recipe": a["base"], "variant": a["variant"], "case_id": bm["case_id"], "team_case_id": f"gen-{bm['case_id']}"},
        "attack": {k: a[k] for k in a if k not in ("id", "group", "benefits", "base", "variant", "expected")},
        "expected_behaviour": a["expected"],
        "expected_settlement": {"overall_verdict": m["expected_verdict"], "policy_payable": m["correct_settlement"]["payable"],
                                "insurer_paid": m["insurer_settlement"]["payable"], "letter_deductions": m["letter_deductions"]},
    }
    os.makedirs(os.path.join(ROOT, "data", "redteam_meta"), exist_ok=True)
    json.dump(meta, open(os.path.join(ROOT, "data", "redteam_meta", f"{a['id']}.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    base_recipe = {**{k: x for k, x in r.items() if k != "variants"},
                   "variant": next(x for x in r["variants"] if x["v"] == a["variant"])}
    write_answer(out, redteam_story(a, meta, r, base_gold(ROOT, meta)), {"attack": a, "base_recipe": base_recipe}, meta)
    return print_jobs, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--answers-only", action="store_true", help="write answer/ from data/redteam_meta; leave the PDFs")
    a = ap.parse_args()
    spec = json.load(open(os.path.join(ROOT, "data", "recipes", "redteam", "attacks.json"), encoding="utf-8"))
    attacks = [x for x in spec["attacks"] if not a.ids or x["id"] in a.ids]
    if a.answers_only:   # (re)write answer/ from data/redteam_meta without rebuilding (and re-dating) the PDFs
        for at in attacks:
            meta = json.load(open(os.path.join(ROOT, "data", "redteam_meta", f"{at['id']}.json"), encoding="utf-8"))
            r = recipe_for(at["base"])
            base_recipe = {**{k: x for k, x in r.items() if k != "variants"},
                           "variant": next(x for x in r["variants"] if x["v"] == at["variant"])}
            write_answer(os.path.join(ROOT, "data", "redteam", at["id"]), redteam_story(at, meta, r, base_gold(ROOT, meta)),
                         {"attack": at, "base_recipe": base_recipe}, meta)
            print(f"{at['id']:<12} answer/ written")
        return 0
    all_jobs, all_problems = [], []
    for at in attacks:
        jobs, problems = build_one(at, a.no_pdf, a.jobs)
        all_jobs += jobs
        all_problems += [f"{at['id']}: {p}" for p in problems]
        print(f"{at['id']:<12} {at['group']:<11} base {at['base']} v{at['variant']}  {'OK' if not problems else 'PROBLEM'}")

    def finish(job):
        hp, pdf, out = job
        if a.no_pdf or not to_pdf(hp, pdf):
            shutil.copy(hp, out)
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        list(ex.map(finish, all_jobs))
    print(f"{len(attacks)} attacks built, {len(all_jobs)} documents, {len(all_problems)} problems")
    for p in all_problems:
        print("  " + p)
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
