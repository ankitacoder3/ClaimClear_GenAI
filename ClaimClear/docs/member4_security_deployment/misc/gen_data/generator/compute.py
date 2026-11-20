"""All money for a case is computed here. The LLM never computes amounts.

build_case(recipe, variant) -> dict with
  facts    : everything the documents show (people, dates, bill lines, earlier claims)
  correct  : assessment under the case's policy wording (generator/wordings.py)
  insurer  : assessment as the insurer's letter shows it (with the planted error, if any)
  tweaks   : document-level changes for not_verifiable / doc_inconsistency cases
  meta     : the hidden label
Amounts are whole rupees. Ratios use exact fractions; rounding is half-up to the rupee.
"""
import copy
import datetime as dt
import hashlib
import random
from fractions import Fraction

from profiles import ANNEX_EXTRAS, PROFILES
from wordings import DEFAULT_WORDING, WORDINGS

SEED = 20261112

def wording(key):
    if key not in WORDINGS:
        raise SystemExit(f"Unknown wording '{key}'. Known: {', '.join(WORDINGS)} (see generator/wordings.py)")
    return WORDINGS[key]


LIST_NAME = {"list1": "List I (not payable)", "list2": "List II (part of room charges)",
             "list3": "List III (part of procedure charges)", "list4": "List IV (part of cost of treatment)"}
PROP_EXEMPT = {"medicines", "ambulance"}  # medicines: 4.1 Note 2. Ambulance: not a hospital charge; own limit.

FIRST_F = ["Ananya", "Kavita", "Meera", "Sunita", "Priya", "Lakshmi", "Neha", "Farzana", "Gurpreet", "Rekha", "Shalini", "Deepa"]
FIRST_M = ["Arvind", "Suresh", "Rakesh", "Imran", "Vikram", "Harish", "Manoj", "Sandeep", "Joseph", "Prakash", "Naveen", "Ravi"]
LAST = ["Kulkarni", "Deshpande", "Iyer", "Nair", "Reddy", "Sharma", "Verma", "Khan", "Patil", "Menon", "Joshi", "Bose", "Gill", "Rao"]
HOSP_A = ["Sanjivani", "Lotus", "Shreeyash", "Arogyam", "Nirmal", "Sahyog", "Navjeevan", "Kaveri", "Prerana", "Suvidha"]
HOSP_B = ["Multispeciality Hospital", "Hospital & Research Centre", "Nursing Home", "Eye Care Hospital", "Medical Centre"]
# Fictional insurer names are fixed per wording in wordings.py.
TPAS = ["MediLink TPA Services Pvt. Ltd.", "CareBridge Health TPA Pvt. Ltd."]


def rhu(x):
    """Round half up to a whole rupee (x may be a Fraction)."""
    x = Fraction(x)
    return int((x * 2 + 1) // 2)


def pct(amount, p):
    return rhu(Fraction(amount) * Fraction(p) / 100)


def d(s):
    return dt.date.fromisoformat(s)


def months_between(a, b):
    """Completed months from date a to date b."""
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        m -= 1
    return m


def add_years(day, n):
    try:
        return day.replace(year=day.year + n)
    except ValueError:
        return day.replace(year=day.year + n, day=28)


def set_path(obj, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        obj = obj[int(k)] if isinstance(obj, list) else obj.setdefault(k, {})
    last = keys[-1]
    if isinstance(obj, list):
        obj[int(last)] = value
    else:
        obj[last] = value


def case_id(recipe, v):
    h = hashlib.sha1(f"{SEED}:{recipe['base_id']}:{v}".encode()).hexdigest()[:6]
    return f"{recipe['split']}-{h}"


# ---- facts --------------------------------------------------------------------------------------
def make_facts(r, v, rng):
    prof = PROFILES[r["procedure"]]
    ins = r["insured"]
    first = (FIRST_F if ins["gender"] == "F" else FIRST_M)
    name = f"{rng.choice(first)} {rng.choice('ABCDGKMNPRSV')}. {rng.choice(LAST)}"
    name = ins.get("name", name)  # a recipe may fix the patient's name
    admit = d(r["admit"])
    nights = sum(s["days"] for s in r["stay"])
    day_care = prof.get("day_care", False) or nights == 0
    discharge = admit + dt.timedelta(days=nights)
    first_inc = d(r["first_inception"])
    if r.get("policy_start"):
        pstart = d(r["policy_start"])
    else:
        pstart = first_inc
        while add_years(pstart, 1) <= admit:
            pstart = add_years(pstart, 1)
    pend = add_years(pstart, 1) - dt.timedelta(days=1)
    si = r["sum_insured"]
    hosp_type = r.get("hospital_type") or ("Eye Care Hospital" if r["procedure"] == "cataract" else None)
    hospital = f"{rng.choice(HOSP_A)} {hosp_type or rng.choice([b for b in HOSP_B if 'Eye' not in b])}"
    hospital = r.get("hospital", hospital)
    style = {
        "bill": rng.choice(["category", "daywise", "summary"]),
        "letter": rng.choice(["cashless", "reimbursement", "tpa"]),
        "money": rng.choice(["symbol", "rs", "inr"]),
        "date": rng.choice(["dmy_dash", "dmy_slash", "long"]),
    }
    style.update(r.get("style", {}))
    if r.get("settlement"):
        style["letter"] = {"cashless": "cashless", "reimbursement": "reimbursement"}.get(r["settlement"], style["letter"])

    # bill lines
    if r.get("lines"):
        lines = copy.deepcopy(r["lines"])
    else:
        total = r.get("bill_total", prof["bill_total"])
        lines = []
        for i, (cat, descs, share) in enumerate(prof["lines"]):
            amt = int(round(total * share * rng.uniform(0.9, 1.1) / 50.0)) * 50
            lines.append({"id": f"{cat[:3]}{i}", "cat": cat, "desc": rng.choice(descs), "amount": amt})
        picks = rng.sample(ANNEX_EXTRAS, rng.randint(1, 3))
        if not r.get("extra_lines"):  # recipe-chosen extras replace the random Annexure A items
            for j, (cat, desc, lo, hi) in enumerate(picks):
                lines.append({"id": f"ax{j}", "cat": cat, "desc": desc, "amount": int(round(rng.uniform(lo, hi) / 10.0)) * 10})
    lines += copy.deepcopy(r.get("extra_lines", []))
    for ln in lines:
        if ln.get("where") == "pre":      # paid outside hospital before admission
            ln["date"] = (admit - dt.timedelta(days=ln["days"])).isoformat()
        elif ln.get("where") == "post":   # paid outside hospital after discharge
            ln["date"] = (discharge + dt.timedelta(days=ln["days"])).isoformat()
        else:
            ln.setdefault("date", (admit + dt.timedelta(days=ln.get("day", 0))).isoformat())

    stay = []
    day = admit
    for s in r["stay"]:
        seg = dict(s)
        seg.setdefault("label", "ICU" if s["ward"] == "icu" else "Room")
        seg["from"] = day.isoformat()
        day = day + dt.timedelta(days=s["days"])
        seg["to"] = day.isoformat()
        stay.append(seg)

    diag = prof["diagnosis"][0] if r.get("diagnosis") is None else r["diagnosis"]
    if r.get("eye"):
        diag = f"{diag}, {r['eye']} eye"
    proc = prof["procedure"][0] + (f", {r['eye']} eye" if r.get("eye") else "")

    surname = name.split()[-1]
    members = []
    for m in ins.get("members", []):
        mm = dict(m)
        mm.setdefault("name", f"{rng.choice(FIRST_F if m['gender'] == 'F' else FIRST_M)} {surname}")
        members.append(mm)
    num = rng.randint(100000, 999999)
    ins_info = wording(r.get("wording", DEFAULT_WORDING))["insurer"]
    return {
        "insurer": ins_info["name"], "insurer_info": ins_info, "tpa": rng.choice(TPAS),
        "uin": ins_info["code"] + wording(r.get("wording", DEFAULT_WORDING))["uin"][3:],
        "policy_no": f"AS/{pstart.year}/{num}/{rng.randint(10, 99)}",
        "member_id": f"MBR-{rng.randint(1000000, 9999999)}-01",
        "claim_no": f"CLM/{admit.year}/{rng.randint(1000000, 9999999)}",
        "insured_name": name, "age": ins["age"], "gender": ins["gender"], "city": ins["city"],
        "cover": ins.get("cover", "individual"), "members": members, "patient_rel": ins.get("rel", "Self"),
        "sum_insured": si, "cb_pct": r.get("cb_pct", 0),
        "first_inception": first_inc.isoformat(), "policy_start": pstart.isoformat(), "policy_end": pend.isoformat(),
        "renewal": pstart > first_inc, "peds_declared": r.get("peds_declared", []),
        "hospital": hospital, "hospital_city": ins["city"], "network": style["letter"] == "cashless",
        "uhid": f"UH{rng.randint(100000, 999999)}", "ip_no": f"IP-{rng.randint(10000, 99999)}",
        "invoice_no": f"INV/{admit.year % 100}-{admit.year % 100 + 1}/{rng.randint(10000, 99999)}",
        "doctor": f"Dr. {rng.choice(FIRST_F + FIRST_M)} {rng.choice(LAST)}",
        "admit": admit.isoformat(), "discharge": discharge.isoformat(), "day_care": day_care,
        "diagnosis": diag, "procedure": proc, "cause": r.get("cause", "illness"),
        "eye": r.get("eye"), "waiting_class": prof["waiting"], "sublimit": prof["sublimit"],
        "wording": r.get("wording", DEFAULT_WORDING),
        "stay": stay, "lines": lines, "prior_claims": copy.deepcopy(r.get("prior_claims", [])),
        "style": style, "letter_date": (discharge + dt.timedelta(days=rng.randint(2, 12) if style["letter"] != "cashless" else 0)).isoformat(),
    }


# ---- assessment ---------------------------------------------------------------------------------
def assess(f, err=None):
    """Settle the claim. err=None follows the wording; otherwise applies the insurer's mistake."""
    e = err or {}
    k = e.get("kind", "")
    W = wording(f["wording"])
    CLAUSE = W["clause"]
    si, cb = f["sum_insured"], pct(f["sum_insured"], f["cb_pct"])
    admit = d(f["admit"])
    res = {"lines": [], "rooms": [], "groups": [], "rejected": None}
    billed = sum(s["rate"] * s["days"] for s in f["stay"]) + sum(l["amount"] for l in f["lines"])
    res["billed"] = billed

    def group(key, label, amount, clause, note_amt=None):
        if amount:
            res["groups"].append({"key": key, "label": label, "amount": amount, "clause": clause, "note_amt": note_amt})

    # 1. eligibility
    cover_m = months_between(d(f["first_inception"]), admit)
    cover_days = (admit - d(f["first_inception"])).days
    reject = None
    if not (d(f["policy_start"]) <= admit <= d(f["policy_end"])):
        reject = ("Admission outside the policy period", CLAUSE["period"])
    elif f["cause"] != "accident" and cover_days < W["wait_first_days"]:
        reject = ("First 30 days waiting period", CLAUSE["wait30"])
    wc = f["waiting_class"]
    if not reject and f["cause"] != "accident" and wc and cover_m < W["wait_months"][wc]:
        reject = (f"Specific waiting period of {W['wait_months'][wc]} months", CLAUSE["wait_spec"])
    if k == "reject_waiting":
        reject = (e.get("basis", "Waiting period"), e.get("clause", CLAUSE["wait_spec"]))
    if k == "nv_missing_cause":
        reject = ("First 30 days waiting period; claim not arising from accident", CLAUSE["wait30"])
    if reject:
        res.update(rejected={"reason": reject[0], "clause": reject[1]}, admissible=0, copay=0, payable=0)
        group("reject", f"Claim not admissible: {reject[0]}", billed, reject[1])
        return res

    # 2. room / ICU caps
    room_cap = min(pct(si, W["room_pct"]), W["room_max"])
    if k == "cap_pct":
        room_cap = min(pct(si, e["pct"]), W["room_max"])
    icu_cap = room_cap if k == "icu_at_room_cap" else min(pct(si, W["icu_pct"]), W["icu_max"])
    ratio = Fraction(1)
    room_allowed = room_excess = 0
    for i, s in enumerate(f["stay"]):
        cap = icu_cap if s["ward"] == "icu" else room_cap
        days_paid = s["days"]
        if k == "icu_days" and s["ward"] == "icu":
            days_paid = e["days"]
        excess_days = s["days"]
        if k == "room_days" and s["ward"] == "room":
            excess_days = e["days"]
        billed_s = s["rate"] * s["days"]
        allowed = min(s["rate"], cap) * days_paid
        if s["rate"] > cap:
            allowed = billed_s - (s["rate"] - cap) * excess_days
            allowed = min(allowed, min(s["rate"], cap) * days_paid)
            ratio = min(ratio, Fraction(cap, s["rate"]))
        res["rooms"].append({"label": s["label"], "ward": s["ward"], "rate": s["rate"], "days": s["days"],
                             "cap": cap, "billed": billed_s, "allowed": allowed})
        room_allowed += allowed
        room_excess += billed_s - allowed
    if k == "prop_wrong_cap":
        rate = max(s["rate"] for s in f["stay"] if s["ward"] == "room")
        ratio = min(Fraction(1), Fraction(e["cap"], rate))
    if k == "prop_wrong_rate":
        ratio = min(Fraction(1), Fraction(room_cap, e["rate"]))
    if k == "prop_on_capped_room" and ratio < 1:
        cut = room_allowed - rhu(room_allowed * ratio)
        room_allowed -= cut
        room_excess += cut
    group("room", "Room / ICU rent above eligible limit", room_excess, CLAUSE["room"] + ", " + CLAUSE["icu"])
    res["room_cap"], res["icu_cap"], res["ratio"] = room_cap, icu_cap, ratio

    # 3. lines: non-payable, proportionate, ambulance
    exempt = set(PROP_EXEMPT)
    if k == "prop_on_medicines":
        exempt.discard("medicines")
    nonpay = prop = amb = 0
    adm_lines = 0
    prop_exact = Fraction(0)  # rounded once per deduction (as the letter shows it), not per line
    for ln in f["lines"]:
        row = {"id": ln["id"], "desc": ln["desc"], "cat": ln["cat"], "billed": ln["amount"], "nonpay": 0, "prop": 0, "limit": 0}
        where = ln.get("where")
        gap = None
        if where == "pre":
            gap = (admit - d(ln["date"])).days
        elif where == "post":
            gap = (d(ln["date"]) - d(f["discharge"])).days
        if ln.get("duplicate_of") and k != "doc_duplicate_line":
            row["nonpay"] = ln["amount"]
            row["reason"] = "duplicate of an earlier bill line (not actually incurred)"
            row["clause"] = "3.28"
        elif where and gap > {"pre": 30, "post": 60}[where]:
            row["nonpay"] = ln["amount"]
            row["reason"] = f"outside {'pre' if where == 'pre' else 'post'}-hospitalisation period ({gap} days)"
            row["clause"] = CLAUSE[where]
        elif ln["cat"].startswith("list"):
            row["nonpay"] = ln["amount"]
            row["reason"] = LIST_NAME[ln["cat"]]
        elif k == "disallow" and ln["id"] == e["line"]:
            row["nonpay"] = ln["amount"]
            row["reason"] = e["reason"]
        else:
            base = ln["amount"]
            if ln["cat"] == "ambulance" and base > W["ambulance_max"]:
                row["limit"] = base - W["ambulance_max"]
                amb += row["limit"]
                base = W["ambulance_max"]
            if ratio < 1 and ln["cat"] not in exempt and not where:
                prop_exact += base - base * ratio
                row["prop"] = base - rhu(base * ratio)  # per-line figure for worksheets only
        row["admissible"] = ln["amount"] - row["nonpay"] - row["prop"] - row["limit"]
        nonpay += row["nonpay"]
        adm_lines += ln["amount"] - row["nonpay"] - row["limit"]
        res["lines"].append(row)
    np_items = [r for r in res["lines"] if r["nonpay"]]
    for r in np_items:
        group("nonpay:" + r["id"], f"{r['desc']} - {r['reason']}", r["nonpay"],
              r.get("clause") or (CLAUSE["nonpay"] if r["cat"].startswith("list") else e.get("clause", CLAUSE["nonpay"])))
    prop = rhu(prop_exact)
    adm_lines -= prop
    group("prop", "Proportionate deduction (room category above eligibility)", prop, CLAUSE["prop"])
    group("ambulance", "Ambulance charges above limit", amb, CLAUSE["ambulance"])
    admissible = room_allowed + adm_lines

    # 4. sub-limits (cataract per eye, modern treatment), using earlier claims this policy year
    pstart, pend = d(f["policy_start"]), d(f["policy_end"])
    prior = [p for p in f["prior_claims"] if pstart <= d(p["date"]) <= pend]
    if f["sublimit"] == "cataract":
        limit = min(pct(si, W["cataract_pct"]), W["cataract_max"])
        used = sum(p["admissible"] for p in prior if p.get("kind") == "cataract" and p["status"] == "settled"
                   and (k == "cataract_shared_eyes" or p.get("eye") == f["eye"]))
        allowed = max(0, limit - used)
        if admissible > allowed:
            group("sublimit", f"Cataract limit ({f['eye']} eye), balance available", admissible - allowed, CLAUSE["cataract"], allowed)
            admissible = allowed
        res["sublimit"] = {"kind": "cataract", "limit": limit, "used": used, "available": allowed}
    if f["sublimit"] == "modern":
        limit = pct(si, e["pct"] if k == "modern_pct" else W["modern_pct"])
        used = sum(p["admissible"] for p in prior if p.get("kind") == "modern" and p["status"] == "settled")
        if k == "nv_unseen_prior":
            used += e["amount"]
        allowed = max(0, limit - used)
        if admissible > allowed:
            group("sublimit", "Modern treatment limit, balance available", admissible - allowed, CLAUSE["modern"], allowed)
            admissible = allowed
        res["sublimit"] = {"kind": "modern", "limit": limit, "used": used, "available": allowed}

    # 5. co-pay
    cp_pct = e["pct"] if k == "copay_pct" else W["copay_pct"]
    cp_base = billed if k == "copay_on_gross" else admissible
    copay = min(pct(cp_base, cp_pct), admissible)
    group("copay", f"Co-payment {cp_pct}%", copay, CLAUSE["copay"])
    after = admissible - copay

    # 6. sum insured still available (earlier claims use up SI by the amount paid - open team question)
    cap_si = si + (0 if k == "cb_ignored" else cb)
    used_si = 0
    for p in prior:
        if k == "prior_at_billed":
            used_si += p["billed"]
        elif k == "prior_rejected_counted" and p["status"] == "rejected":
            used_si += p["billed"]
        elif p["status"] == "settled":
            used_si += p["paid"]
    available = max(0, cap_si - used_si)
    payable = min(after, available)
    group("si", "Sum insured balance for the policy year", after - payable, CLAUSE["si"], available)
    res["si"] = {"si": si, "cb": 0 if k == "cb_ignored" else cb, "used": used_si, "available": available}

    # 6b. a fee taken under a clause that is not in the wording (red-team: fake clause)
    if k == "processing_fee":
        fee = pct(payable, e["pct"])
        group("fee", f"Processing fee {e['pct']}%", fee, e.get("clause", ""))
        payable -= fee

    # 7. unexplained deductions (not verifiable cases)
    if k in ("nv_lumpsum", "nv_tariff", "nv_room_lumpsum", "nv_missing_annexure"):
        label = {"nv_lumpsum": "Other deductions as per policy terms and conditions",
                 "nv_tariff": "Deduction as per network tariff agreement",
                 "nv_room_lumpsum": "Room and nursing charges - deduction as per eligibility",
                 "nv_missing_annexure": "Pharmacy items not payable as per annexure"}[k]
        amt = min(e["amount"], payable)
        group("other", label, amt, e.get("clause", ""))
        payable -= amt

    res.update(admissible=admissible, copay=copay, payable=payable)
    return res


# ---- document tweaks and label ------------------------------------------------------------------
def doc_tweaks(f, err):
    k = (err or {}).get("kind", "")
    t = {}
    if k == "doc_date_mismatch":
        t[err.get("where", "letter_discharge")] = err["date"]
    if k == "doc_total_mismatch":
        t["bill_total_extra"] = err["extra"]
    if k == "doc_subtotal_mismatch":
        t["subtotal_extra"] = {"cat": err["cat"], "extra": err["extra"]}
    if k == "nv_missing_annexure":
        t["pharmacy_annexure_missing"] = err.get("line", "med")
    if k == "nv_room_lumpsum":
        t["room_lumpsum"] = True
    if k == "nv_missing_cause":
        t["hide_cause"] = True
    if k == "doc_duplicate_line":
        t["duplicate_line"] = err["line"]
    if k == "doc_line_after_discharge":
        t["line_date"] = {"line": err["line"], "date": (d(f["discharge"]) + dt.timedelta(days=err.get("days", 1))).isoformat()}
    return t


def group_map(res):
    return {g["key"]: g for g in res["groups"]}


def build_case(recipe, variant):
    r = copy.deepcopy(recipe)
    for path, val in (variant.get("set") or {}).items():
        set_path(r, path, val)
    rng = random.Random(f"{SEED}:{recipe['base_id']}")  # base-level: variants share people and hospital
    f = make_facts(r, variant["v"], rng)
    err = variant.get("insurer_error")
    correct = assess(f)
    insurer = assess(f, err)
    tweaks = doc_tweaks(f, err)
    cg, ig = group_map(correct), group_map(insurer)
    # Expected verdict for every deduction as it appears in the insurer's letter.
    vtype = variant["type"]
    kind = (err or {}).get("kind", "")
    own = {"prop_on_medicines": {"prop"}, "prop_wrong_cap": {"prop"}, "prop_wrong_rate": {"prop"},
           "prop_on_capped_room": {"room"}, "cap_pct": {"room"}, "icu_at_room_cap": {"room"}, "icu_days": {"room"},
           "room_days": {"room"}, "copay_pct": {"copay"}, "copay_on_gross": {"copay"},
           "prior_at_billed": {"si"}, "prior_rejected_counted": {"si"}, "cb_ignored": {"si"},
           "cataract_shared_eyes": {"sublimit"}, "modern_pct": {"sublimit"}, "reject_waiting": {"reject"},
           "disallow": {"nonpay:" + (err or {}).get("line", "")},
           "nv_unseen_prior": {"sublimit"}, "nv_lumpsum": {"other"}, "nv_tariff": {"other"},
           "nv_room_lumpsum": {"other"}, "processing_fee": {"fee"}, "nv_missing_annexure": {"other"}, "nv_missing_cause": {"reject"}}.get(kind, set())
    deductions = []
    for g in insurer["groups"]:
        right = cg.get(g["key"], {}).get("amount", 0)
        if g["key"] == "other" or (vtype == "not_verifiable" and g["key"] in own and g["amount"] != right):
            verdict = "not_verifiable"
        elif g["amount"] == right:
            verdict = "matches"
        elif g["key"] not in own and right != 0:  # a deduction with no basis at all is disputable
            verdict = "consequential"   # method right; amount moved only because the mistake was elsewhere
        else:
            verdict = "disputable"
        deductions.append({"deduction": g["label"], "clause_cited": g["clause"], "amount": g["amount"],
                           "verdict": verdict, "correct_amount": right})
    # Deductions the policy requires but the letter left out (only when the letter rejects or misses a step).
    missing = [{"deduction": g["label"], "clause": g["clause"], "correct_amount": g["amount"]}
               for key, g in cg.items() if key not in ig and not insurer["rejected"]]
    diffs = []
    for key in sorted(set(cg) | set(ig)):
        a, b = cg.get(key, {}).get("amount", 0), ig.get(key, {}).get("amount", 0)
        if a != b:
            g = ig.get(key) or cg.get(key)
            diffs.append({"deduction": g["label"], "clause": g["clause"], "correct": a, "insurer": b, "excess_deducted": b - a})
    meta = {
        "case_id": case_id(recipe, variant["v"]), "base_id": recipe["base_id"], "variant": variant["v"],
        "tag": recipe["tag"], "split": recipe["split"], "planted_type": vtype,
        "insurer_error": err, "wording": f["wording"], "wording_uin": wording(f["wording"])["uin"],
        "correct_settlement": {"billed": correct["billed"], "admissible": correct["admissible"],
                               "copay": correct["copay"], "payable": correct["payable"],
                               "rejected": correct["rejected"]},
        "insurer_settlement": {"admissible": insurer["admissible"], "copay": insurer["copay"],
                               "payable": insurer["payable"], "rejected": insurer["rejected"]},
        "underpaid_by": correct["payable"] - insurer["payable"],
        "letter_deductions": deductions,
        "deductions_missing_from_letter": missing,
        "wrong_deductions": diffs,
        "expected_verdict": ("not_verifiable" if vtype == "not_verifiable" else
                             "inconsistent_documents" if vtype == "doc_inconsistency" else
                             "matches" if vtype == "none" else "disputable"),
        "doc_tweaks": tweaks,
        "open_question_flags": (["si_depletion_by_paid"] if f["prior_claims"] else []),
        "story": recipe["story"],
    }
    return {"facts": f, "correct": correct, "insurer": insurer, "tweaks": tweaks, "meta": meta}
