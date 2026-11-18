"""Compare gold worksheets (data/gold/<case_id>/gold.json) with the generator's answers (data/meta/<case_id>.json):
payable, insurer's payout, overall verdict and the verdict for each settlement-letter line.

  py -3 generator/compare_gold.py
"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "gold")
META = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "meta")
rows, issues = [], []
for mp in sorted(glob.glob(os.path.join(META, "*.json"))):
    m = json.load(open(mp, encoding="utf-8"))
    cid = m["case_id"]
    gp = os.path.join(GOLD, cid, "gold.json")
    tag = f"{m['base_id']} v{m['variant']} {m['planted_type']}"
    if not os.path.exists(gp):
        issues.append(f"{cid} {tag}: NO GOLD")
        continue
    try:
        g = json.load(open(gp, encoding="utf-8"))
    except ValueError:
        issues.append(f"{cid} {tag}: gold file unreadable (still being written?)")
        continue
    gen_pay, gold_pay = m["correct_settlement"]["payable"], g.get("payable")
    gen_ins, gold_ins = m["insurer_settlement"]["payable"], g.get("insurer_paid")
    gen_ov, gold_ov = m["expected_verdict"], g.get("overall")
    probs = []
    if gold_pay != gen_pay:
        probs.append(f"payable gold {gold_pay} vs gen {gen_pay} (diff {None if gold_pay is None else gold_pay - gen_pay})")
    if gold_ins != gen_ins:
        probs.append(f"insurer_paid read as {gold_ins} vs letter {gen_ins}")
    if gold_ov != gen_ov:
        probs.append(f"overall gold {gold_ov} vs gen {gen_ov}")
    gl = {d["amount"]: d["verdict"] for d in g.get("letter_deductions", [])}
    for d in m["letter_deductions"]:
        gv = gl.get(d["amount"])
        if gv is not None and gv != d["verdict"]:
            probs.append(f"line '{d['deduction'][:45]}' {d['amount']}: gold {gv} vs gen {d['verdict']}")
    rows.append((m["tag"], cid, tag, not probs))
    if probs:
        issues.append(f"{cid} {tag}:\n    " + "\n    ".join(probs) + (f"\n    gold notes: {g.get('notes', '')[:300]}" if g.get("notes") else ""))
ok = sum(1 for r in rows if r[3])
print(f"{len(rows)} compared, {ok} agree fully, {len(issues)} with differences or missing")
for t in ("MD", "SK", "Holdout"):
    sub = [r for r in rows if r[0] == t]
    print(f"  {t}: {sum(1 for r in sub if r[3])}/{len(sub)} agree")
print()
print("\n".join(issues))
