"""The uploaded documents must agree with each other: plain code over each document's fact sheet (read from page 1
at upload by ``ui_chainlit/identify.py``). No model, so it is free and predictable.

* ``pick_current_letter``: with more than one settlement letter, the one for this hospital stay (same patient and
  admission date as the bill, then the newest) is the current one; the others are earlier claims (bug #3)
* ``check``: patient, policy number, sum insured and dates compared across bill, letter and schedule; an "earlier"
  letter for this same stay is a claim counted twice (red-team RT-A12, RT-D01, D02, D04, D05)

Each document is ``{"document_id", "name", "type", "facts": {patient_name, policy_no, claim_no, document_date,
admission_date, discharge_date, hospital, sum_insured, endorsements}}``.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from .input_guard import Finding

TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "kumari", "master", "baby", "late"}
DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y",
                "%d %B %Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y", "%d %b, %Y"]


# --------------------------------------------------------------------------- reading the facts

def name_tokens(name: Optional[str]) -> list[str]:
    words = re.findall(r"[a-z]+", (name or "").lower())
    return [w for w in words if w not in TITLES]


def same_person(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    """True/False when both names are printed; None when one is missing. Initials match full names ("D" ~ "Dev")."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return None
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)

    def fits(t: str) -> bool:
        return any(t == u or (len(t) == 1 and u.startswith(t)) or (len(u) == 1 and t.startswith(u)) for u in long)
    full = [t for t in short if len(t) > 1]
    return bool(full) and all(fits(t) for t in short)


def number(text: Optional[str]) -> Optional[float]:
    """The first amount in the text ("Rs. 2,50,000/-" -> 250000; the dot in "Rs." is not a decimal point)."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def day(text: Optional[str]) -> Optional[date]:
    t = re.sub(r"\s+", " ", (text or "").strip().replace(",", ", ").replace(" ,", ",")).strip()
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def policy_key(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def facts(doc: dict) -> dict:
    return doc.get("facts") or {}


# --------------------------------------------------------------------------- which settlement letter is current

def pick_current_letter(docs: list[dict]) -> dict:
    """``{"current", "earlier": [...], "reason", "ambiguous"}`` (``current`` is None when there is no letter)."""
    letters = [d for d in docs if d.get("type") == "settlement_letter"]
    if len(letters) <= 1:
        return {"current": letters[0]["document_id"] if letters else None, "earlier": [], "reason": "", "ambiguous": False}
    bill = next((facts(d) for d in docs if d.get("type") == "bill"), {})
    bill_adm = day(bill.get("admission_date"))

    def score(d):
        f = facts(d)
        s = 2 * bool(same_person(f.get("patient_name"), bill.get("patient_name")))
        s += 2 * bool(bill_adm and day(f.get("admission_date")) == bill_adm)
        newest = day(f.get("document_date")) or date.min
        return s, newest
    ranked = sorted(letters, key=score, reverse=True)
    top, second = score(ranked[0]), score(ranked[1])
    ambiguous = top == second or (top[0] == 0 and top[1] == date.min)
    reason = ("matches the bill's patient and admission date" if top[0] >= 4 else
              "matches the bill's admission date" if top[0] >= 2 else "the newest letter")
    return {"current": ranked[0]["document_id"], "earlier": [d["document_id"] for d in ranked[1:]],
            "reason": reason, "ambiguous": ambiguous}


def earlier_summary(doc: dict) -> str:
    f = facts(doc)
    bits = [f"claim {f['claim_no']}" if f.get("claim_no") else "", f"dated {f['document_date']}" if f.get("document_date") else "",
            f"admitted {f['admission_date']}" if f.get("admission_date") else ""]
    return "Earlier settlement letter (a previous claim)" + (": " + ", ".join(b for b in bits if b) if any(bits) else "")


# --------------------------------------------------------------------------- the documents must agree

def check(docs: list[dict], current_letter: Optional[str] = None) -> list[Finding]:
    """Disagreements between the bill, the current letter, the schedule and earlier letters."""
    by = {}
    for d in docs:
        if d.get("type") == "settlement_letter" and current_letter and d["document_id"] != current_letter:
            by.setdefault("earlier", []).append(d)
        elif d.get("type") in ("bill", "settlement_letter", "policy_schedule") and d.get("type") not in by:
            by[d["type"]] = d
    bill, letter, schedule = by.get("bill"), by.get("settlement_letter"), by.get("policy_schedule")
    out: list[Finding] = []

    def add(where, snippet, reason):
        out.append(Finding("consistency", where, snippet, reason, "consistency"))

    for a, b in ((bill, schedule), (letter, schedule), (letter, bill)):
        if a and b and same_person(facts(a).get("patient_name"), facts(b).get("patient_name")) is False:
            add(f"{a['name']} vs {b['name']}", f"{facts(a)['patient_name']} / {facts(b)['patient_name']}",
                "the patient's name differs")
    for a in (letter, bill):
        pa, ps = policy_key(facts(a).get("policy_no")) if a else "", policy_key(facts(schedule).get("policy_no")) if schedule else ""
        if pa and ps and pa != ps:
            add(f"{a['name']} vs {schedule['name']}", f"{facts(a)['policy_no']} / {facts(schedule)['policy_no']}",
                "the policy number differs")
    if letter and schedule:
        sl, ss = number(facts(letter).get("sum_insured")), number(facts(schedule).get("sum_insured"))
        if sl and ss and abs(sl - ss) >= 1:
            add(f"{letter['name']} vs {schedule['name']}",
                f"{facts(letter)['sum_insured']} / {facts(schedule)['sum_insured']}",
                "the sum insured differs (the schedule is the policy's own record)")
    if letter and bill:
        for field, label in (("admission_date", "admission date"), ("discharge_date", "discharge date")):
            dl, db = day(facts(letter).get(field)), day(facts(bill).get(field))
            if dl and db and dl != db:
                add(f"{letter['name']} vs {bill['name']}", f"{facts(letter)[field]} / {facts(bill)[field]}",
                    f"the {label} differs")
    current_adm = day(facts(letter).get("admission_date")) if letter else None
    current_adm = current_adm or (day(facts(bill).get("admission_date")) if bill else None)
    for e in by.get("earlier", []):
        if current_adm and day(facts(e).get("admission_date")) == current_adm:
            add(f"{e['name']}", f"admitted {facts(e)['admission_date']}",
                "this 'earlier' claim is for the same hospital stay: it must not be counted twice")
    return out


def message(findings: list[Finding]) -> str:
    """Plain message for the user (no model needed)."""
    if not findings:
        return ""
    lines = ["**⚠️ Your documents don't agree**", ""]
    lines += [f"- {f.where}: {f.reason} ({f.snippet})" for f in findings]
    lines += ["", "Please check you uploaded the right documents. I'll go on, but I'll treat these points with care "
                  "(for the sum insured I use your policy schedule)."]
    return "\n".join(lines)
