"""The app's upload step: store uploaded documents as a new case, and extract the claim and letter if possible.

    .venv/bin/python scripts/upload_case.py FILE[=ROLE] ...         # prints one JSON object
    .venv/bin/python scripts/upload_case.py --purge                 # delete every uploaded case and its data

Run with the servers' environment (it writes to the case store and uses the settlement engine's models). Used by
the web UI (``claimclear_graph.webapp``); the running case-records server sees the new case immediately.

* **Roles** come from ``=ROLE`` or the file name (``bill``, ``settlement_letter``, ``policy_schedule``,
  ``discharge_summary``, ``policy_wording``, ``other_bills``, ``earlier_settlement``); anything else is ``other``.
* **Policy number** is read from the policy schedule, else from the letter or the bill.
* **Extraction** (the claim and letter the settlement engine needs), first that applies:

  1. the letter is a known **development dataset** document: the engine's own stand-in for it (labelled
     ``dataset document (development stand-in)``);
  2. the PDFs have the table layout of the gen-data letters and bills: parsed from the PDF tables;
  3. nothing: ``extraction`` is ``null`` and the graph's LLM extractor (if an API key is configured) reads them.

Output: ``{"case_id", "policy_no", "documents": [{name, role, document_id}], "extraction": {claim, letter} | null,
"how": str, "warnings": [str]}``, or ``{"error": str}``.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "servers" / "case_records"))
sys.path.insert(0, str(REPO / "servers" / "settlement_engine"))

import os  # noqa: E402

import pymupdf  # noqa: E402

from case_records.store import ROLES, CaseStore  # noqa: E402

NAME_ROLES = {"bill": "bill", "itemised_bill": "bill", "other_bills": "bill", "settlement_letter": "settlement_letter",
              "letter": "settlement_letter", "policy_schedule": "policy_schedule", "schedule": "policy_schedule",
              "discharge_summary": "discharge_summary", "policy_wording": "policy_wording", "wording": "policy_wording",
              "earlier_settlement": "other"}
VAR = Path(os.environ.get("CLAIMCLEAR_VAR") or REPO / "var")       # runtime data (tests point it elsewhere)
POLICY_NO = re.compile(r"Policy (?:No\.?|number|Number)\s*[:\-]?\s*([A-Za-z0-9ЀА-я\-/‐-―]{6,})")


def role_of(path: Path, given: str = "") -> str:
    if given:
        return given if given in ROLES else "other"
    stem = re.sub(r"^\d+_", "", path.stem.lower())
    stem = re.sub(r"_\d+$", "", stem)
    return NAME_ROLES.get(stem, "other")


def pdf_text(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        with pymupdf.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def policy_number(files: dict[Path, str]) -> str:
    for wanted in ("policy_schedule", "settlement_letter", "bill"):
        for path, role in files.items():
            if role == wanted:
                found = POLICY_NO.search(pdf_text(path))
                if found:
                    return found.group(1)
    return ""


def dataset_match(document_id: str) -> str:
    """The dataset key of a document already in the development dataset (``SET-01``, ``gen-dev-x/letter.pdf``)."""
    for map_path in (VAR / "dataset_map.json", VAR / "dev_cases" / "dataset_map.json"):
        if map_path.exists():
            for key, v in json.loads(map_path.read_text(encoding="utf-8")).items():
                if v.get("document_id") == document_id:
                    return key
    return ""


def gen_layout_payload(files: dict[Path, str]) -> dict | None:
    """The gen-data PDF table parser (``development/dev_eval/dev_cases/extract.py``) on the uploaded bill(s) and letter."""
    sys.path.insert(0, str(REPO / "development" / "dev_eval" / "dev_cases"))
    import extract  # noqa: E402  (the evaluation's parser: rebuilds table rows from word positions)
    bills = [p for p, r in files.items() if r == "bill" and p.suffix.lower() == ".pdf"]
    letters = sorted((p for p, r in files.items() if r == "settlement_letter" and p.suffix.lower() == ".pdf"),
                     key=lambda p: ("settlement_letter" not in p.name.lower() or "earlier" in p.name.lower(), p.name))
    if not bills or not letters:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        shutil.copy(bills[0], folder / "bill.pdf")
        if len(bills) > 1:
            shutil.copy(bills[1], folder / "other_bills.pdf")
        shutil.copy(letters[0], folder / "settlement_letter.pdf")
        try:
            out = extract.gen_payload(folder)
        except Exception:
            return None
    if not out.get("claim", {}).get("lines") or not out.get("letter", {}).get("paid_amount"):
        return None
    return json.loads(json.dumps(out, default=str))


def purge() -> dict:
    """Delete the user's data: every case that isn't a registered development case, the files no remaining case
    uses, the extracted-text cache (it holds document text) and the dry-run portal's record of filings.

    Uploaded medical records are personal data: ClaimClear keeps them only while it is running (start.py calls
    this when the web UI closes, and at start-up in case a previous run was killed)."""
    store = CaseStore()
    dataset_cases = set()
    map_path = VAR / "dataset_map.json"
    if map_path.exists():
        dataset_cases = {v["case_id"] for v in json.loads(map_path.read_text(encoding="utf-8")).values()}
    uploads = [cid for cid in store._cases if cid not in dataset_cases]
    for cid in uploads:
        del store._cases[cid]
    still_used = {d for c in store._cases.values() for d in c.document_ids}
    files = 0
    for doc_id in [d for d in store._docs if d not in still_used]:
        rec = store._docs.pop(doc_id)
        path = store.blobs.path(rec.stored_name)
        if path is not None and Path(path).exists():
            Path(path).unlink()
            files += 1
    store._save()
    cache = store.root / "text_cache"
    if uploads and cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    portal = Path(os.environ.get("CLAIMCLEAR_PORTAL_STORE") or VAR / "insurer_portal" / "dry_run.json")
    filings = 0
    if portal.exists():
        filings = len(json.loads(portal.read_text(encoding="utf-8") or "{}"))
        portal.unlink()
    checkpoints = VAR / "graph"
    if checkpoints.exists():
        shutil.rmtree(checkpoints, ignore_errors=True)
    return {"cases_deleted": len(uploads), "files_deleted": files, "filings_deleted": filings}


def main(argv: list[str]) -> dict:
    if argv == ["--purge"]:
        return purge()
    files: dict[Path, str] = {}
    for arg in argv:
        name, _, role = arg.partition("=")
        path = Path(name)
        if not path.is_file():
            return {"error": f"no such file: {name}"}
        files[path] = role_of(path, role)
    if not files:
        return {"error": "no files"}
    if "settlement_letter" not in files.values():
        return {"error": "please include the settlement letter (name it settlement_letter.pdf or pick its role)"}
    policy_no = policy_number(files)
    warnings = []
    if not policy_no:
        return {"error": "no policy number found in the policy schedule, letter or bill"}
    store = CaseStore()
    reference_key = ""
    letters = [p for p, r in files.items() if r == "settlement_letter"]
    # several letters (e.g. an earlier settlement marked as a letter): the one named like a settlement letter wins
    letter_path = next((p for p in letters if "settlement_letter" in p.name.lower() and "earlier" not in p.name.lower()),
                       letters[0])
    if len(letters) > 1:
        warnings.append(f"{len(letters)} settlement letters: checking {letter_path.name}")
    import hashlib
    letter_id = "doc_" + hashlib.sha256(letter_path.read_bytes()).hexdigest()[:16]
    match = dataset_match(letter_id)
    if "/" in match:
        reference_key = match.split("/", 1)[0]          # gen-data case: its own policy record in the reference data
    case = store.create_case(policy_no, reference_key=reference_key)
    docs = []
    for path, role in files.items():
        try:
            rec = store.add_document(case.case_id, path, role=role)
        except Exception as exc:                          # e.g. an unsupported file type: keep the rest
            warnings.append(f"{path.name}: {exc}")
            continue
        docs.append({"name": path.name, "role": role, "document_id": rec.document_id})

    extraction, how = None, ""
    if match.startswith("SET-"):
        from mcp_server.__main__ import case_payload_for
        extraction = json.loads(json.dumps(case_payload_for(match), default=str))
        how = f"dataset document {match} (development stand-in for the LLM extraction)"
    if extraction is None:
        extraction = gen_layout_payload(files)
        if extraction:
            how = "parsed from the PDF tables"
    if extraction is None:
        how = "not extracted here: needs the document reader's LLM (set an API key)"
    return {"case_id": case.case_id, "policy_no": policy_no, "documents": docs, "extraction": extraction,
            "how": how, "warnings": warnings}


if __name__ == "__main__":
    try:
        result = main(sys.argv[1:])
    except Exception as exc:                              # reported to the UI, never a traceback page
        result = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
