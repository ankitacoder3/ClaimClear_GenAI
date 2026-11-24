"""Remove what the security check flagged from an uploaded PDF, and nothing else. Not a PII scrubber: names, amounts,
metadata and the rest of the document stay as they are. Runs once per flagged file, in the upload flow only, with the
servers' Python (it has PyMuPDF):

    python scrub.py '{"path": "in.pdf", "out": "clean.pdf", "snippets": ["..."]}'   ->  {"path", "removed", "not_found"}

Each flagged snippet is looked for wherever the reader found it: page text (visible or hidden) is redacted (white
fill), and a metadata value, annotation, form field or attachment holding it is cleared or deleted.
"""
from __future__ import annotations

import json
import re
import sys


def chunks(snippet: str) -> list[str]:
    """The snippet, then its sentences and lines (PDF search works within a line), longest first."""
    parts = [snippet] + re.split(r"(?<=[.!?])\s+|\n+", snippet)
    return [p.strip() for p in dict.fromkeys(parts) if len(p.strip()) >= 12]


def norm(text) -> str:
    return " ".join(str(text or "").split()).lower()


def holds(value, snippet: str) -> bool:
    v, s = norm(value), norm(snippet)
    return bool(v and s) and (s in v or (len(v) >= 12 and v in s))


def scrub(path: str, out: str, snippets: list[str]) -> dict:
    import pymupdf
    doc = pymupdf.open(path)
    if not doc.is_pdf:
        return {"error": "not a PDF"}
    removed, not_found = [], []
    meta = dict(doc.metadata or {})
    for snippet in snippets:
        hit = False
        flat = " ".join(snippet.split())
        for piece in chunks(flat):                                # page text, visible or hidden
            for page in doc:
                for rect in page.search_for(piece):
                    page.add_redact_annot(rect)                    # white fill: the text is gone, no black box
                    hit = True
            if hit and piece == flat:
                break
        for k, v in meta.items():                                  # a metadata value holding it
            if holds(v, snippet):
                meta[k], hit = "", True
        for page in doc:                                           # annotations and form fields holding it
            for a in list(page.annots() or []):
                if a.type[0] != pymupdf.PDF_ANNOT_REDACT and holds(a.info.get("content"), snippet):
                    page.delete_annot(a)
                    hit = True
            for w in list(page.widgets() or []):
                if holds(w.field_value, snippet):
                    w.field_value = ""
                    w.update()
                    hit = True
        for name in list(doc.embfile_names()):                     # attachments holding it
            try:
                data = doc.embfile_get(name).decode("utf-8", "ignore")
            except Exception:                                      # noqa: BLE001  unreadable attachment: leave it
                continue
            if holds(data, snippet) or holds(name, snippet):
                doc.embfile_del(name)
                hit = True
        (removed if hit else not_found).append(snippet)
    for page in doc:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    doc.set_metadata(meta)
    doc.save(out, garbage=3, deflate=True)
    return {"path": out, "removed": removed, "not_found": not_found}


if __name__ == "__main__":
    p = json.loads(sys.argv[1])
    try:
        print(json.dumps(scrub(p["path"], p["out"], p.get("snippets", []))))
    except Exception as exc:                   # noqa: BLE001  the caller decides what to do with an unreadable file
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
