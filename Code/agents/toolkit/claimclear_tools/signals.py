"""Turning tool results into graph decisions.

Each function reads one tool's structured result and returns where the graph
should go next. Use them in LangGraph conditional edges, so the routing rules
live in one tested place instead of in prompts.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Route names (strings, so they can be used directly as LangGraph edge labels).
OK = "ok"
MISSING_DOCUMENT = "missing_document"
ASK_USER = "ask_user"
AUDIT_ROWS = "audit_rows"
NOT_ADMISSIBLE = "not_admissible"
REPLAN = "replan"
DONE = "done"
OFFER_GRIEVANCE = "offer_grievance"
NO_GRIEVANCE = "no_grievance"


# --------------------------------------------------------------------------- case-records


def unreadable_pages(document_text: dict) -> list[int]:
    """Pages of a ``get_document_text`` result that couldn't be read (OCR unavailable or failed)."""
    return [p["page"] for p in document_text.get("pages", []) if p.get("ocr_status") in ("unavailable", "failed")]


def after_document_text(document_text: dict) -> str:
    """``missing_document`` if any page couldn't be read, else ``ok``. Never guess figures from an unread page."""
    return MISSING_DOCUMENT if unreadable_pages(document_text) else OK


def visible_text(document_text: dict) -> str:
    """All pages' visible text, for the extraction prompt. Hidden text is deliberately left out."""
    return "\n\n".join(f"[page {p['page']}]\n{p['text']}" for p in document_text.get("pages", []) if p.get("text"))


def security_flags(document_text: dict) -> list[str]:
    """Definite anomalies a reader can't see on the page: hidden text, hidden form fields, annotations,
    attachments, edited-PDF flags. Empty for an ordinary document. For logging and the guardrails (Member 4)."""
    flags = []
    for p in document_text.get("pages", []):
        reasons = sorted({r for s in p.get("spans", []) for r in s.get("hidden_reasons", [])})
        if reasons:
            flags.append(f"page {p['page']}: hidden text ({', '.join(reasons)})")
    if document_text.get("annotations"):
        flags.append(f"{len(document_text['annotations'])} annotation(s)")
    if any(f.get("hidden") for f in document_text.get("form_fields", [])):
        flags.append("hidden form field")
    if document_text.get("attachments"):
        flags.append(f"{len(document_text['attachments'])} attachment(s)")
    flags.extend(f"pdf: {f}" for f in document_text.get("pdf_flags", []))
    return flags


def untrusted_channels(document_text: dict) -> dict[str, str]:
    """Every non-visible text channel, keyed by where it came from, for the injection checker (Member 4).

    Includes hidden page text, metadata values, annotation contents, form-field values and attachment
    previews. Ordinary documents have metadata too, so presence alone is not a warning; scan the text.
    """
    out: dict[str, str] = {}
    for p in document_text.get("pages", []):
        if p.get("hidden_text"):
            out[f"page{p['page']}.hidden_text"] = p["hidden_text"]
    for k, v in (document_text.get("metadata") or {}).items():
        if v and k not in ("creationDate", "modDate"):
            out[f"metadata.{k}"] = v
    for i, a in enumerate(document_text.get("annotations", []), start=1):
        if a.get("content"):
            out[f"annotation{i}"] = a["content"]
    for f in document_text.get("form_fields", []):
        if f.get("value"):
            out[f"form_field.{f.get('name', '')}"] = f["value"]
    for a in document_text.get("attachments", []):
        if a.get("text_preview"):
            out[f"attachment.{a.get('name', '')}"] = a["text_preview"]
    return out


# --------------------------------------------------------------------------- settlement-engine


def after_settlement(settlement: dict) -> str:
    """Route after ``expected_settlement``: ``ask_user``, ``not_admissible`` or ``audit_rows``."""
    status = settlement.get("status")
    if status == "needs_information":
        return ASK_USER
    if status == "not_admissible":
        return NOT_ADMISSIBLE
    return AUDIT_ROWS


def rows_to_audit(letter: dict) -> list[str]:
    """Row IDs to pass to ``reproduce_deduction``: the letter's rows, plus COPAY or REJECTION when present."""
    ids = [r["row_id"] for r in letter.get("rows", [])]
    if letter.get("letter_type") == "rejection":
        ids.append("REJECTION")
    elif letter.get("copay_amount") is not None:
        ids.append("COPAY")
    return ids


def after_row_audit(row: dict) -> str:
    """Route after ``reproduce_deduction``.

    * ``replan``: nothing matched but not every hypothesis was tested; call again without ``hypothesis_ids``.
    * ``ask_user``: the row carries a tie question (``Q-TIE-...``) to ask the policyholder.
    * ``done``: a final verdict for this row (a ``Q-BREAKDOWN-...`` question is advice for the user, not a stop).
    """
    if row.get("verdict") == "not_verifiable" and row.get("exhaustive") is False:
        return REPLAN
    if any(q.get("question_id", "").startswith("Q-TIE-") for q in row.get("questions", [])):
        return ASK_USER
    return DONE


def questions_to_ask(settlement: Optional[dict] = None, rows: Iterable[dict] = ()) -> list[dict]:
    """Questions to put to the policyholder (via ``interrupt()``), without duplicates or advice on what to ask
    the insurer (``Q-BREAKDOWN-...``, ``Q-ITEMS-...``; see ``breakdown_requests``)."""
    out: list[dict] = []
    seen = set()
    for q in list((settlement or {}).get("questions", [])) + [q for r in rows for q in r.get("questions", [])]:
        qid = q.get("question_id", "")
        if qid.startswith(INSURER_QUESTIONS) or qid in seen:
            continue
        seen.add(qid)
        out.append(q)
    return out


def disputable_rows(rows: Iterable[dict]) -> list[dict]:
    """Rows a grievance may cover: ``does_not_match_policy`` with a positive difference."""
    return [r for r in rows if r.get("verdict") == "does_not_match_policy" and (r.get("difference") or 0) > 0]


# Questions for the insurer, not the policyholder: how a figure was worked out, which items make it up.
INSURER_QUESTIONS = ("Q-BREAKDOWN-", "Q-ITEMS-")


def breakdown_requests(rows: Iterable[dict]) -> list[dict]:
    """Rows where the user should ask the insurer for its working or its item list (``Q-BREAKDOWN-...``,
    ``Q-ITEMS-...``): material for the grievance letter."""
    return [r for r in rows if any(q.get("question_id", "").startswith(INSURER_QUESTIONS) for q in r.get("questions", []))]


def bill_inconsistencies(letter_audit: dict) -> list[dict]:
    """Charges the bill repeats for the same day that the insurer paid twice (no letter row removes them).

    The documents disagree with themselves, so the overall verdict is ``inconsistent_documents``: ask the
    hospital or insurer whether the service was really given twice before calling it an overpayment.
    """
    if any(r.get("kind") == "duplicate" for r in letter_audit.get("rows", [])):
        return []
    return [d for d in (letter_audit.get("settlement") or {}).get("deductions", []) if d.get("kind") == "duplicate_line"]


def after_letter_audit(letter_audit: dict) -> str:
    """``offer_grievance`` only when some rupees may be disputable; otherwise ``no_grievance``."""
    amount = letter_audit.get("disputable_amount")
    return OFFER_GRIEVANCE if amount is not None and amount > 0 else NO_GRIEVANCE
