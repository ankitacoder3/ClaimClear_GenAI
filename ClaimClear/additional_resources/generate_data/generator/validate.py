"""Check every built case.

  py -3 generator/validate.py            # all cases
  py -3 generator/validate.py H17 H18    # only these stories

Checks: bill lines add up to the bill total (unless a total mismatch is planted); the letter's arithmetic
adds up; the planted error changes the result (except clean, not-verifiable and inconsistency cases); no label
or metadata text in documents; synthetic footer present; no real-looking ID numbers; no unfilled placeholders;
metadata not inside data/cases; gold worksheets (if present in data/gold/<case_id>/gold.json) agree with meta.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from compute import assess  # noqa: E402
from render import FOOTER  # noqa: E402
from wordings import WORDINGS  # noqa: E402

LABEL_WORDS = ["planted", "insurer_error", "variant", "base_id", "ground truth", "gold", "metadata", "correct settlement",
               "underpaid", "not_verifiable", "doc_inconsistency", "prop_on", "copay_on", "reject_waiting", "label:"]
REAL_ID = [re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),         # Aadhaar-like
           re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),             # PAN-like
           re.compile(r"\b[6-9]\d{9}\b")]                     # Indian mobile-like


def main(only=None):
    """only: optional list of base ids (e.g. ["H17"]) to check just those stories."""
    problems, n = [], 0
    for mp in sorted(glob.glob(os.path.join(ROOT, "data", "meta", "*.json"))):
        m = json.load(open(mp, encoding="utf-8"))
        cid = m["case_id"]
        if only and m["base_id"] not in only:
            continue
        n += 1
        bd = os.path.join(HERE, "_build", cid)
        f = json.load(open(os.path.join(bd, "_facts.json"), encoding="utf-8"))
        kind = (m["insurer_error"] or {}).get("kind", "")

        def bad(msg):
            problems.append(f"{cid} ({m['base_id']} v{m['variant']}): {msg}")

        # 1. totals reconcile
        billed = sum(s["rate"] * s["days"] for s in f["stay"]) + sum(l["amount"] for l in f["lines"])
        if billed != m["correct_settlement"]["billed"]:
            bad("bill lines do not add up to billed amount")
        for who, err in (("correct", None), ("insurer", m["insurer_error"])):
            r = assess(f, err)
            if r["billed"] - sum(g["amount"] for g in r["groups"]) != r["payable"]:
                bad(f"{who} letter arithmetic does not add up")
        # 2. planted error is detectable
        c, i = m["correct_settlement"]["payable"], m["insurer_settlement"]["payable"]
        if m["planted_type"] == "none" and (c != i or m["wrong_deductions"]):
            bad("clean case but insurer differs from correct")
        if m["planted_type"] not in ("none", "doc_inconsistency") and not m["wrong_deductions"] and not m["doc_tweaks"]:
            bad("planted error has no effect (if the insurer is right, set type to 'none'; otherwise change the "
                "numbers so this insurer_error changes the settlement)")
        if m["planted_type"] not in ("none", "not_verifiable", "doc_inconsistency") and i >= c:
            bad("insurer does not underpay (pick an error or numbers that make the insurer pay less)")
        # 3. documents: no label leak, footer, no real IDs, no placeholders
        case_dir = os.path.join(ROOT, "data", "cases", m["split"], cid)
        if any(x.endswith(".json") for x in os.listdir(case_dir)):
            bad("json file inside case folder")
        if not any(x.startswith("00_policy_wording.") for x in os.listdir(case_dir)):
            bad("policy wording copy missing")
        W = WORDINGS[f["wording"]]
        wh = os.path.join(HERE, "_wordings", f"{f['wording']}_{f['insurer_info']['short']}.html")
        if os.path.exists(wh) and re.search(W["residue"], open(wh, encoding="utf-8").read(), re.I):
            bad("policy wording copy still names the original insurer")
        if f["uin"] not in open(os.path.join(bd, "01_policy_schedule.html"), encoding="utf-8").read():
            bad("schedule UIN does not match the wording copy")
        for hp in glob.glob(os.path.join(bd, "*.html")):
            text = open(hp, encoding="utf-8").read()
            visible = re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", text, flags=re.S))
            low = visible.lower()
            for w in LABEL_WORDS:
                if w in low:
                    bad(f"{os.path.basename(hp)} contains '{w}'")
            for w in (m["base_id"], cid):  # whole word only: 'H1' must not match 'UH1234'
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", visible, re.I):
                    bad(f"{os.path.basename(hp)} contains '{w}'")
            if FOOTER not in text:
                bad(f"{os.path.basename(hp)} missing synthetic footer")
            for rx in REAL_ID:
                if rx.search(re.sub(r"<[^>]+>", " ", text)):
                    bad(f"{os.path.basename(hp)} has a real-looking ID: {rx.search(text)}")
            if re.search(r"\{[a-z_]+\}", text):
                bad(f"{os.path.basename(hp)} has an unfilled placeholder")
        # 4. gold agrees with generator (gold is written by the cross-checker)
        gp = os.path.join(ROOT, "data", "gold", cid, "gold.json")
        if os.path.exists(gp):
            g = json.load(open(gp, encoding="utf-8"))
            if g.get("payable") != c:
                bad(f"gold payable {g.get('payable')} != generator {c}")
    print(f"{n} cases checked, {len(problems)} problems")
    for p in problems:
        print("  " + p)
    return problems


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1:] or None) else 0)
