"""Make a clean copy of an uploaded PDF before it is stored: redact the given snippets (flagged instructions and every
hidden-text run the reader reported), then strip what a reader cannot see (metadata, comments and annotations, form
fields, attachments, JavaScript, invisible-mode text). Runs with the servers' Python, which has PyMuPDF:

    python scrub.py '{"path": "in.pdf", "out": "clean.pdf", "snippets": ["..."]}'   ->  {"path", "removed", "not_found"}
"""
from __future__ import annotations

import json
import re
import sys


def chunks(snippet: str) -> list[str]:
    """The snippet, then its sentences and lines (PDF search works within a line), longest first."""
    parts = [snippet] + re.split(r"(?<=[.!?])\s+|\n+", snippet)
    return [p.strip() for p in dict.fromkeys(parts) if len(p.strip()) >= 12]


def scrub(path: str, out: str, snippets: list[str]) -> dict:
    import pymupdf
    doc = pymupdf.open(path)
    if not doc.is_pdf:
        return {"error": "not a PDF"}
    removed, not_found = [], []
    for snippet in snippets:
        hit = False
        for piece in chunks(" ".join(snippet.split())):
            for page in doc:
                for rect in page.search_for(piece):
                    page.add_redact_annot(rect)            # white fill: the text is gone, no black box
                    hit = True
            if hit and piece == " ".join(snippet.split()):
                break
        (removed if hit else not_found).append(snippet)
    for page in doc:
        page.apply_redactions()
    doc.scrub()
    doc.save(out, garbage=4, deflate=True)
    return {"path": out, "removed": removed, "not_found": not_found}


if __name__ == "__main__":
    p = json.loads(sys.argv[1])
    try:
        print(json.dumps(scrub(p["path"], p["out"], p.get("snippets", []))))
    except Exception as exc:                   # noqa: BLE001  the caller decides what to do with an unreadable file
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
