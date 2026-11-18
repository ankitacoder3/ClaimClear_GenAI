"""Render a computed case into HTML documents (policy schedule, itemised bill, settlement letter,
earlier settlement letters). All amounts come from compute.py. Optional prose overrides written by an
LLM live in data/prose/<case_id>.json and may only use the placeholders listed in PROSE_KEYS."""
import datetime as dt
import html
import json
import os
import random

from compute import d, wording

FOOTER = "SYNTHETIC SAMPLE: fictional hospital, insurer and patient. Created for capstone evaluation. Not a real document."

PROSE_KEYS = {
    "letter_opening": "{name} {claim_no} {hospital}",
    "letter_closing": "{insurer} {grievance_days}",
    "bill_note": "{hospital}",
}
DEFAULT_PROSE = {
    "letter_opening": [
        "We have processed the claim of {name} (Claim No. {claim_no}) for treatment at {hospital}. The settlement is set out below.",
        "Reference your claim No. {claim_no} in respect of {name}. After scrutiny of the documents submitted by {hospital}, the claim has been assessed as follows.",
        "This is to inform you that claim {claim_no} for {name}, treated at {hospital}, has been processed under the policy terms.",
    ],
    "letter_closing": [
        "If you are not satisfied with this settlement you may write to the Grievance Cell of {insurer} within {grievance_days} days of this letter.",
        "For any query or grievance, please contact {insurer} Grievance Redressal Officer within {grievance_days} days, quoting the claim number.",
    ],
    "bill_note": [
        "This is a computer generated invoice from {hospital}. Rates are inclusive of applicable taxes.",
        "All charges inclusive of taxes. Subject to local jurisdiction. Thank you for choosing {hospital}.",
    ],
}

CAT_TITLE = {
    "room": "Room & Nursing", "icu": "ICU Charges", "surgeon": "Professional Fees", "anaesthetist": "Professional Fees",
    "consultant": "Professional Fees", "ot": "Operation Theatre", "implant": "Implants", "medicines": "Pharmacy",
    "consumables": "Consumables", "diagnostics": "Investigations", "blood": "Blood & Blood Products", "oxygen": "Oxygen & Gases",
    "physio": "Physiotherapy", "nursing": "Room & Nursing", "ambulance": "Ambulance", "list1": "Miscellaneous",
    "list2": "Administrative & Miscellaneous", "list3": "Consumables", "list4": "Administrative & Miscellaneous",
}


def money(n, style):
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    sign = "-" if n < 0 else ""
    return {"symbol": f"{sign}₹{s}.00", "rs": f"{sign}Rs. {s}/-", "inr": f"{sign}INR {s}.00"}[style]


def date(s, style):
    x = d(s) if isinstance(s, str) else s
    return {"dmy_dash": x.strftime("%d-%b-%Y"), "dmy_slash": x.strftime("%d/%m/%Y"),
            "long": f"{x.day} {x.strftime('%B %Y')}"}[style]


def esc(x):
    return html.escape(str(x))


CSS = """
body{font-family:Arial,Helvetica,sans-serif;font-size:11.5px;color:#111;margin:28px}
h1{font-size:17px;margin:0} h2{font-size:13px;margin:16px 0 6px;border-bottom:1px solid #999}
table{border-collapse:collapse;width:100%;margin:6px 0} td,th{border:1px solid #bbb;padding:4px 6px;vertical-align:top}
th{background:#eee;text-align:left} td.n,th.n{text-align:right;white-space:nowrap}
.hdr{display:flex;justify-content:space-between;border-bottom:2px solid #333;padding-bottom:8px;margin-bottom:10px}
.small{font-size:10px;color:#444} .foot{margin-top:22px;font-size:9.5px;color:#666;border-top:1px solid #ccc;padding-top:4px}
.kv td:first-child{width:34%;background:#fafafa} .tot td{font-weight:bold} .pb{page-break-before:always}
"""


def page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body>{body}<div class='foot'>{FOOTER}</div></body></html>")


def load_prose(case_id, f, rng, prose_dir):
    vals = {"name": f["insured_name"], "claim_no": f["claim_no"], "hospital": f["hospital"],
            "insurer": f["insurer"], "grievance_days": 15}
    custom = {}
    path = os.path.join(prose_dir, f"{case_id}.json")
    if os.path.exists(path):
        custom = json.load(open(path, encoding="utf-8"))
    out = {}
    for key in PROSE_KEYS:
        text = custom.get(key) or rng.choice(DEFAULT_PROSE[key])
        out[key] = text.format(**vals)
    return out


# ---- policy schedule ----------------------------------------------------------------------------
def schedule(f):
    st = f["style"]
    M = lambda n: money(n, st["money"])
    D = lambda s: date(s, st["date"])
    W = wording(f["wording"])
    C = W["clause"]
    rows = [("Policy number", f["policy_no"]), ("Product", "Arogya Sanjeevani Policy"), ("UIN", f["uin"]),
            ("Policy wording", f"Arogya Sanjeevani Policy wording, UIN {f['uin']} (copy enclosed)"),
            ("Policy type", "Renewal" if f["renewal"] else "New"), ("Cover", "Family floater" if f["cover"] == "floater" else "Individual"),
            ("Period of insurance", f"{D(f['policy_start'])} to {D(f['policy_end'])}"),
            ("Date of first inception (continuous cover since)", D(f["first_inception"])),
            ("Sum insured", M(f["sum_insured"])), ("Cumulative bonus", f"{f['cb_pct']}% ({M(f['sum_insured'] * f['cb_pct'] // 100)})"),
            ("Co-payment", f"{W['copay_pct']}% on every claim (Clause {C['copay']})"),
            ("Room rent limit", f"{W['room_pct']}% of sum insured, max {M(W['room_max'])} per day (Clause {C['room']})"),
            ("ICU limit", f"{W['icu_pct']}% of sum insured, max {M(W['icu_max'])} per day (Clause {C['icu']})")]
    people = [(f["insured_name"], f["patient_rel"], f["age"], "M" if f["gender"] == "M" else "F", ", ".join(f["peds_declared"]) or "None")]
    for m in f["members"]:
        people.append((m["name"], m["rel"].title(), m["age"], m["gender"], "None"))
    body = (f"<div class='hdr'><div><h1>{esc(f['insurer'])}</h1><div class='small'>Health Insurance Division (fictional)</div></div>"
            f"<div><b>POLICY SCHEDULE</b><br><span class='small'>Issued {D(f['policy_start'])}</span></div></div>"
            "<table class='kv'>" + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in rows) + "</table>"
            "<h2>Insured persons</h2><table><tr><th>Name</th><th>Relationship</th><th>Age</th><th>Gender</th><th>Pre-existing disease declared</th></tr>"
            + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{c}</td><td>{g}</td><td>{esc(p)}</td></tr>" for a, b, c, g, p in people)
            + f"</table><p class='small'>Proposer address: {esc(f['city'])}. Member ID {esc(f['member_id'])}. "
            "This schedule must be read with the policy wording. Waiting periods, exclusions and sub-limits apply as per the wording.</p>")
    return page("Policy Schedule", body)


# ---- itemised bill ------------------------------------------------------------------------------
def bill_rows(f, tw):
    """Return list of (date, category, description, qty, rate, amount)."""
    rows = []
    if tw.get("room_lumpsum"):
        total = sum(s["rate"] * s["days"] for s in f["stay"])
        rows.append((f["admit"], "room", "Room, boarding & nursing charges", 1, total, total))
    else:
        for s in f["stay"]:
            rows.append((s["from"], s["ward"], f"{s['label']} - room rent", s["days"], s["rate"], s["rate"] * s["days"]))
    for ln in f["lines"]:
        if ln.get("where"):
            continue  # pre/post-hospitalisation receipts are a separate document
        desc = ln["desc"]
        if tw.get("pharmacy_annexure_missing") == ln["id"]:
            desc = "Pharmacy (details as per annexure enclosed)"
        day = tw.get("line_date", {}).get("date") if tw.get("line_date", {}).get("line") == ln["id"] else ln["date"]
        rows.append((day, ln["cat"], desc, 1, ln["amount"], ln["amount"]))
    return rows


def bill(f, tw, prose):
    st = f["style"]
    M = lambda n: money(n, st["money"])
    D = lambda s: date(s, st["date"])
    layout = "category" if tw.get("subtotal_extra") else "daywise" if tw.get("line_date") else st["bill"]
    rows = bill_rows(f, tw)
    total = sum(r[5] for r in rows)
    printed_total = total + tw.get("bill_total_extra", 0)
    admit_shown = tw.get("bill_admit", f["admit"])
    head = (f"<div class='hdr'><div><h1>{esc(f['hospital'])}</h1><div class='small'>{esc(f['hospital_city'])} (fictional)</div></div>"
            f"<div><b>{'FINAL BILL / ITEMISED INVOICE' if layout != 'summary' else 'IN-PATIENT FINAL BILL'}</b><br>"
            f"<span class='small'>Invoice {esc(f['invoice_no'])}<br>Date {D(f['discharge'])}</span></div></div>"
            "<table class='kv'>"
            f"<tr><td>Patient</td><td>{esc(f['insured_name'])} ({f['age']} / {f['gender']})</td></tr>"
            f"<tr><td>UHID / IP No.</td><td>{esc(f['uhid'])} / {esc(f['ip_no'])}</td></tr>"
            f"<tr><td>Admission / Discharge</td><td>{D(admit_shown)} / {D(f['discharge'])}{' (day care)' if f['day_care'] else ''}</td></tr>"
            f"<tr><td>Diagnosis</td><td>{esc(f['diagnosis'])}</td></tr><tr><td>Procedure</td><td>{esc(f['procedure'])}</td></tr>"
            f"<tr><td>Treating doctor</td><td>{esc(f['doctor'])}</td></tr>"
            f"<tr><td>Payer</td><td>{'Cashless - ' + esc(f['tpa']) if st['letter'] == 'cashless' else 'Self / reimbursement'}</td></tr></table>")
    if layout == "daywise":
        body = "<h2>Day-wise charges</h2><table><tr><th>Date</th><th>Particulars</th><th class='n'>Qty</th><th class='n'>Rate</th><th class='n'>Amount</th></tr>"
        expanded = []
        for r in rows:
            if r[1] in ("room", "icu") and r[3] > 1:
                for i in range(r[3]):
                    day = (d(r[0]) + dt.timedelta(days=i)).isoformat()
                    expanded.append((day, r[1], r[2].replace(" - room rent", f" - day {i + 1}"), 1, r[4], r[4]))
            else:
                expanded.append(r)
        expanded.sort(key=lambda r: r[0])
        body += "".join(f"<tr><td>{D(r[0])}</td><td>{esc(r[2])}</td><td class='n'>{r[3]}</td><td class='n'>{M(r[4])}</td><td class='n'>{M(r[5])}</td></tr>" for r in expanded)
        body += f"<tr class='tot'><td colspan='4'>Gross total</td><td class='n'>{M(printed_total)}</td></tr></table>"
    else:
        groups = {}
        for r in rows:
            groups.setdefault(CAT_TITLE.get(r[1], "Other"), []).append(r)
        if layout == "summary":
            body = "<h2>Bill summary</h2><table><tr><th>Head</th><th class='n'>Amount</th></tr>"
            body += "".join(f"<tr><td>{esc(g)}</td><td class='n'>{M(sum(x[5] for x in rs))}</td></tr>" for g, rs in groups.items())
            body += f"<tr class='tot'><td>Total</td><td class='n'>{M(printed_total)}</td></tr></table>"
            body += "<h2 class='pb'>Annexure: item details</h2>"
        else:
            body = ""
        body += "<table><tr><th>Sl.</th><th>Particulars</th><th class='n'>Qty</th><th class='n'>Rate</th><th class='n'>Amount</th></tr>"
        n = 0
        for g, rs in groups.items():
            body += f"<tr><th colspan='5'>{esc(g)}</th></tr>"
            for r in rs:
                n += 1
                body += f"<tr><td>{n}</td><td>{esc(r[2])}</td><td class='n'>{r[3]}</td><td class='n'>{M(r[4])}</td><td class='n'>{M(r[5])}</td></tr>"
            sub = sum(x[5] for x in rs)
            se = tw.get("subtotal_extra")
            if se and any(x[1] == se["cat"] for x in rs):
                sub += se["extra"]
            if layout == "category":
                body += f"<tr><td></td><td><i>Sub-total {esc(g)}</i></td><td></td><td></td><td class='n'><i>{M(sub)}</i></td></tr>"
        body += f"<tr class='tot'><td colspan='4'>Grand total</td><td class='n'>{M(printed_total)}</td></tr></table>"
    body += f"<p class='small'>{esc(prose['bill_note'])}</p>"
    return page("Itemised Hospital Bill", head + body)


# ---- settlement letter --------------------------------------------------------------------------
def letter(f, res, tw, prose):
    st = f["style"]
    M = lambda n: money(n, st["money"])
    D = lambda s: date(s, st["date"])
    kind = st["letter"]
    title = {"cashless": "CASHLESS AUTHORISATION - FINAL APPROVAL", "reimbursement": "CLAIM SETTLEMENT ADVICE",
             "tpa": "CLAIM SETTLEMENT STATEMENT"}[kind]
    issuer = f["tpa"] if kind == "tpa" else f["insurer"]
    discharge_shown = tw.get("letter_discharge", f["discharge"])
    to = (f"The Medical Superintendent / TPA Desk<br>{esc(f['hospital'])}, {esc(f['hospital_city'])}" if kind == "cashless"
          else f"{esc(f['insured_name'])}<br>{esc(f['city'])}")
    kv = [("Claim number", f["claim_no"]), ("Policy number", f["policy_no"]), ("Patient", f"{f['insured_name']}, {f['age']} yrs"),
          ("Hospital", f["hospital"]), ("Admission / discharge", f"{D(tw.get('letter_admit', f['admit']))} / {D(discharge_shown)}"),
          ("Diagnosis", f["diagnosis"]), ("Sum insured", M(f["sum_insured"]))]
    body = (f"<div class='hdr'><div><h1>{esc(issuer)}</h1><div class='small'>Claims Department (fictional)"
            f"{' - on behalf of ' + esc(f['insurer']) if kind == 'tpa' else ''}</div></div>"
            f"<div><b>{title}</b><br><span class='small'>Date {D(f['letter_date'])}</span></div></div>"
            f"<p>To,<br>{to}</p><p>{esc(prose['letter_opening'])}</p>"
            "<table class='kv'>" + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in kv) + "</table>")
    if res["rejected"]:
        body += (f"<h2>Decision</h2><p>The claim for {M(res['billed'])} is <b>not admissible</b>. Reason: "
                 f"{esc(res['rejected']['reason'])} (Clause {esc(res['rejected']['clause'])} of the policy wording).</p>"
                 f"<table><tr class='tot'><td>Amount payable</td><td class='n'>{M(0)}</td></tr></table>")
    else:
        body += ("<h2>Assessment</h2><table><tr><th>Particulars</th><th>Policy reference</th><th class='n'>Amount</th></tr>"
                 f"<tr><td>Total amount claimed</td><td></td><td class='n'>{M(res['billed'])}</td></tr>")
        for g in res["groups"]:
            label = g["label"] + (f" {M(g['note_amt'])}" if g.get("note_amt") is not None else "")
            ref = f"Clause {g['clause']}" if g["clause"] else "-"
            body += f"<tr><td>Less: {esc(label)}</td><td>{esc(ref)}</td><td class='n'>{M(-g['amount'])}</td></tr>"
        body += f"<tr class='tot'><td colspan='2'>Net amount payable</td><td class='n'>{M(res['payable'])}</td></tr></table>"
        if kind == "cashless":
            body += f"<p>The hospital may collect only {M(res['billed'] - res['payable'])} from the patient towards amounts not payable under the policy.</p>"
        else:
            body += f"<p>The amount of {M(res['payable'])} will be credited by NEFT to the bank account registered under the policy.</p>"
    body += f"<p>{esc(prose['letter_closing'])}</p><p>Authorised signatory<br>{esc(issuer)}</p>"
    return page("Settlement Letter", body)


def prior_letter(f, p, i):
    st = f["style"]
    M = lambda n: money(n, st["money"])
    D = lambda s: date(s, st["date"])
    patient = f["insured_name"] if p.get("member", "self") == "self" else f"{p['member'].title()} of {f['insured_name']}"
    rows = [("Claim number", f"{f['claim_no'][:-3]}{100 + i}"), ("Policy number", f["policy_no"]), ("Patient", patient),
            ("Date of admission", D(p["date"])), ("Diagnosis / procedure", p["diagnosis"]), ("Amount claimed", M(p["billed"]))]
    if p["status"] == "rejected":
        rows += [("Decision", "Claim not admissible under policy terms"), ("Amount paid", M(0))]
    else:
        rows += [("Amount admitted", M(p["admissible"])), (f"Co-payment {wording(f['wording'])['copay_pct']}% (Clause {wording(f['wording'])['clause']['copay']})", M(p["admissible"] - p["paid"])), ("Amount paid", M(p["paid"]))]
    body = (f"<div class='hdr'><div><h1>{esc(f['insurer'])}</h1><div class='small'>Claims Department (fictional)</div></div>"
            f"<div><b>CLAIM SETTLEMENT ADVICE</b><br><span class='small'>Date {D((d(p['date']) + dt.timedelta(days=14)).isoformat())}</span></div></div>"
            "<table class='kv'>" + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in rows) + "</table>")
    return page("Earlier Settlement Letter", body)


def other_bills(f):
    """Receipts paid outside the hospital before admission or after discharge."""
    st = f["style"]
    M = lambda n: money(n, st["money"])
    D = lambda s: date(s, st["date"])
    shops = {"diagnostics": "Precise Diagnostics Lab (fictional)", "medicines": "Wellcare Pharmacy (fictional)",
             "consultant": f"Clinic of {f['doctor']}"}
    rows = [l for l in f["lines"] if l.get("where")]
    body = (f"<div class='hdr'><div><h1>Other bills submitted with the claim</h1>"
            f"<div class='small'>Patient {esc(f['insured_name'])} · Claim {esc(f['claim_no'])}</div></div></div>"
            "<table><tr><th>Date</th><th>Issued by</th><th>Particulars</th><th class='n'>Amount</th></tr>"
            + "".join(f"<tr><td>{D(l['date'])}</td><td>{esc(shops.get(l['cat'], 'Outpatient clinic (fictional)'))}</td>"
                      f"<td>{esc(l['desc'])}</td><td class='n'>{M(l['amount'])}</td></tr>" for l in rows)
            + f"<tr class='tot'><td colspan='3'>Total</td><td class='n'>{M(sum(l['amount'] for l in rows))}</td></tr></table>")
    return page("Other Bills", body)


def render_case(case, prose_dir):
    f, tw = case["facts"], case["tweaks"]
    rng = random.Random(case["meta"]["case_id"])
    prose = load_prose(case["meta"]["case_id"], f, rng, prose_dir)
    docs = {"01_policy_schedule.html": schedule(f), "02_itemised_bill.html": bill(f, tw, prose),
            "03_settlement_letter.html": letter(f, case["insurer"], tw, prose)}
    for i, p in enumerate(f["prior_claims"]):
        docs[f"04_earlier_settlement_{i + 1}.html"] = prior_letter(f, p, i)
    if any(l.get("where") for l in f["lines"]):
        docs["05_other_bills.html"] = other_bills(f)
    return docs
