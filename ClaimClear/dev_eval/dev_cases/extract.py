"""DEV STAND-IN for the document reader agent's extraction: the claim and the letter of every case in a split.

    .venv/Scripts/python.exe dev_eval/dev_cases/extract.py dev var/dev_cases/extracted_dev.json

The real graph extracts the bill and the settlement letter with an LLM (Member 3's document reader).
For a whole-application run without an LLM this script gives the same ``{"claim", "letter"}`` tool
arguments, so every other step runs for real:

* synthetic cases (``syn-``): from the documents' extracted fields in the case's answer file (only
  what is printed on the bill and the letter: line items, totals, letter rows; never the expected
  verdicts or amounts);
* gen-data cases (``gen-``): parsed from the PDFs themselves (table rows rebuilt from word
  positions): the bill's item rows (and ``other_bills.pdf``), the letter's assessment rows, its
  co-payment, or the rejection reason.

Run it with the servers' environment (``.venv``): it builds the payloads with the settlement engine's
own models, so they have exactly the tool schemas' shape.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "servers" / "settlement_engine"))

import pymupdf  # noqa: E402

from engine.dataset import claim_from_invoice, load_letter  # noqa: E402
from engine.models import BillLine, Claim, LetterRow, SettlementLetter  # noqa: E402
from mcp_server.convert import claim_payload, letter_payload  # noqa: E402

DATASET = REPO / "dev_data" / "dataset"
MONEY = re.compile(r"^-?\s*(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)\s*(?:/-)?$")
DATE = re.compile(r"(\d{1,2}-[A-Z][a-z]{2}-\d{4}|\d{2}/\d{2}/\d{4}|\d{1,2} [A-Z][a-z]+ \d{4})")


# --------------------------------------------------------------------------- PDF rows


def rows(path: Path) -> list[list[str]]:
    """The document as table rows: words on one line, split into cells at wide gaps."""
    out: list[list[str]] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            line: list = []
            y = None
            for w in sorted(page.get_text("words"), key=lambda w: (w[1], w[0])):
                if y is None or abs(w[1] - y) > 3:
                    if line:
                        out.append(_cells(line))
                    line, y = [w], w[1]
                else:
                    line.append(w)
            if line:
                out.append(_cells(line))
    return out


def _cells(words, gap: float = 12) -> list[str]:
    cells, cur, last = [], [], None
    for w in sorted(words, key=lambda w: w[0]):
        if last is not None and w[0] - last > gap:
            cells.append(" ".join(cur))
            cur = []
        cur.append(w[4])
        last = w[2]
    cells.append(" ".join(cur))
    return cells


def money(text: str):
    m = MONEY.match(text.strip())
    return Decimal(m.group(1).replace(",", "")) if m else None


def date(text: str):
    m = DATE.search(text or "")
    if not m:
        return None
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(m.group(1), fmt).date()
        except ValueError:
            continue
    return None


def field(table: list[list[str]], label: str) -> str:
    for r in table:
        if len(r) >= 2 and r[0].lower().startswith(label.lower()):
            return r[1]
    return ""


# --------------------------------------------------------------------------- gen-data bills and letters


def bill_lines(path: Path, start: int = 1) -> tuple[list[BillLine], Decimal | None, Decimal]:
    """Item rows (``[date] [sl] particulars qty rate amount``), the printed grand total and any discount."""
    lines, total, discount = [], None, Decimal(0)
    for r in rows(path):
        amounts = [money(c) for c in r]
        label = r[0].lower()
        if re.match(r"^(grand |gross |net )?total", label) and amounts[-1] is not None:
            total = amounts[-1]
            continue
        if "discount" in label and amounts[-1] is not None:
            discount += amounts[-1]
            continue
        if len(r) == 4 and DATE.fullmatch(r[0]) and amounts[-1] is not None and amounts[-2] is None:
            # other bills: date, issued by, particulars, amount (pre- and post-hospitalisation expenses)
            lines.append(BillLine(line_id=f"L{start + len(lines):02d}", description=f"{r[2]} ({r[1]})",
                                  amount=amounts[-1], qty=Decimal(1), rate=amounts[-1], date=date(r[0])))
            continue
        if len(r) < 4 or amounts[-1] is None or amounts[-2] is None or not re.match(r"^\d+(\.\d+)?$", r[-3]):
            continue                                   # a header, a summary row (head, amount) or text
        cells = r[:-3]
        line_date = date(cells[0]) if cells and DATE.fullmatch(cells[0]) else None
        if line_date:
            cells = cells[1:]
        if cells and re.fullmatch(r"\d+", cells[0]):
            cells = cells[1:]                          # the serial number
        lines.append(BillLine(line_id=f"L{start + len(lines):02d}", description=" ".join(cells), amount=amounts[-1],
                              qty=Decimal(r[-3]), rate=amounts[-2], date=line_date))
    return lines, total, discount


def gen_payload(case_dir: Path) -> dict:
    bill = rows(case_dir / "bill.pdf")
    letter_rows = rows(case_dir / "settlement_letter.pdf")
    lines, total, discount = bill_lines(case_dir / "bill.pdf")
    if (case_dir / "other_bills.pdf").exists():
        more, more_total, more_discount = bill_lines(case_dir / "other_bills.pdf", start=len(lines) + 1)
        lines += more
        discount += more_discount
        total = (total or Decimal(0)) + (more_total or sum((l.amount for l in more), Decimal(0)))
    adm_dis = field(bill, "Admission")
    dates = [date(p) for p in adm_dis.split(" / ")] if adm_dis else []
    claim_no = field(letter_rows, "Claim number")
    claim = Claim(claim_id=claim_no or case_dir.name, policy_no=field(letter_rows, "Policy number"),
                  admission=dates[0] if dates else None, discharge=dates[1] if len(dates) > 1 else None,
                  lines=tuple(lines), diagnosis=field(bill, "Diagnosis"), procedure=field(bill, "Procedure"),
                  discount=discount, printed_total=total)

    text = " ".join(" ".join(r) for r in letter_rows)
    if "not admissible" in text.lower():
        claimed = re.search(r"claim for (\S+) is not admissible", text)
        reason = re.search(r"Reason:\s*(.+?)(?:\s+Amount payable|$)", text)
        letter = SettlementLetter(letter_id=claim_no, letter_type="rejection",
                                  claimed_amount=money(claimed.group(1).rstrip(".")) if claimed else claim.printed_total,
                                  rows=(), paid_amount=Decimal(0), copay_amount=None,
                                  rejection_reason=reason.group(1).strip() if reason else "")
        return {"claim": claim_payload(claim), "letter": letter_payload(letter)}

    claimed = paid = copay = None
    out_rows: list[LetterRow] = []
    last = None
    for r in letter_rows:
        amt = money(r[-1]) if r else None
        label = r[0]
        low = label.lower()
        if low.startswith("total amount claimed") and amt is not None:
            claimed = amt
        elif ("amount payable" in low or "net amount" in low or "amount approved" in low) and amt is not None:
            paid = amt
        elif low.startswith("less") and amt is not None:
            particulars = re.sub(r"^less:?\s*", "", label, flags=re.I)
            reason = r[1] if len(r) > 2 else ""
            if "co-pay" in low or "copay" in low:
                copay = amt
                last = None
            else:
                last = LetterRow(row_id=f"R{len(out_rows) + 1}", particulars=particulars, amount=amt, reason=reason)
                out_rows.append(last)
        elif last is not None and len(r) == 1 and amt is None and not low.startswith(("net", "the amount")):
            out_rows[-1] = LetterRow(row_id=last.row_id, particulars=f"{last.particulars} {label}", amount=last.amount,
                                     reason=last.reason)             # particulars wrapped onto the next line
            last = out_rows[-1]
        else:
            last = None
    letter = SettlementLetter(letter_id=claim_no, letter_type="settlement", claimed_amount=claimed or claim.printed_total,
                              rows=tuple(out_rows), paid_amount=paid if paid is not None else Decimal(0),
                              copay_amount=copay, rejection_reason="")
    return {"claim": claim_payload(claim), "letter": letter_payload(letter)}


# --------------------------------------------------------------------------- synthetic cases


def syn_payload(answer: dict) -> dict:
    docs = answer["source_answer"]
    ids = answer["documents"]
    bill = docs[ids[next(n for n in ids if n.startswith("bill"))]]
    letter_id = ids.get("settlement_letter.pdf")
    claim_id = docs[letter_id]["document"].get("claim_no") if letter_id else bill["doc_id"]
    out = {"claim": claim_payload(claim_from_invoice(bill["invoices"][0], claim_id or bill["doc_id"]))}
    if letter_id:
        out["letter"] = letter_payload(load_letter(letter_id))
    return out


def extract(split: str) -> dict:
    out = {}
    for path in sorted((DATASET / split / "answers").glob("*.json")):
        answer = json.loads(path.read_text(encoding="utf-8"))
        case_id = answer["case_id"]
        try:
            if answer["source"] == "claimclear-synthetic":
                out[case_id] = {**syn_payload(answer), "extraction": "dataset records (printed fields only)"}
            else:
                out[case_id] = {**gen_payload(DATASET / split / "cases" / case_id), "extraction": "parsed from the PDFs"}
        except Exception as exc:                       # reported, never hidden
            out[case_id] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


if __name__ == "__main__":
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "var" / "dev_cases" / f"extracted_{split}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = extract(split)
    target.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    errors = [k for k, v in result.items() if "error" in v]
    print(f"{len(result)} cases extracted to {target}; errors: {errors or 'none'}")
