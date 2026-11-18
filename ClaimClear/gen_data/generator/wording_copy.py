"""Make the policy-wording copy that goes into each case folder.

The text of the original wording PDF is kept word for word (pdftotext -layout). Only the strings listed in
wordings.py "rebrand" are swapped for the case's fictional insurer: company name, short name, website, e-mail,
address, toll-free numbers and UIN. The result is printed back to PDF. Copies are cached per wording + insurer
in generator/_wordings/.
"""
import html
import os
import re
import shutil
import subprocess

from wordings import WORDINGS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "_wordings")
PDFTOTEXT = [shutil.which("pdftotext"), r"C:\Program Files\Git\mingw64\bin\pdftotext.exe", "/usr/bin/pdftotext"]

CSS = ("body{margin:0} pre{font-family:'Courier New',monospace;font-size:8.6px;line-height:1.25;margin:22px 26px;"
       "white-space:pre-wrap} .pb{page-break-after:always}")


def extract_text(pdf):
    exe = next((p for p in PDFTOTEXT if p and os.path.exists(p)), None)
    if not exe:
        raise SystemExit("pdftotext not found (install poppler or Git for Windows)")
    out = subprocess.run([exe, "-enc", "UTF-8", "-layout", pdf, "-"], capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def rebrand(key, ins, uin):
    W = WORDINGS[key]
    text = extract_text(os.path.join(ROOT, W["pdf"]))
    vals = dict(ins, uin=uin)
    for old, new in W["rebrand"]:
        text = text.replace(old, new.format(**vals))
    left = sorted(set(m.group(0) for m in re.finditer(W["residue"], text, re.I)))
    if left:
        raise SystemExit(f"Wording {key}: original identifiers left after rebrand: {left}. Add them to 'rebrand'.")
    return text


def wording_pdf(key, ins, uin, to_pdf):
    """Return (path, kind) of the cached rebranded wording; kind is 'pdf' or 'html'."""
    os.makedirs(CACHE, exist_ok=True)
    base = os.path.join(CACHE, f"{key}_{ins['short']}")
    if os.path.exists(base + ".pdf"):
        return base + ".pdf", "pdf"
    pages = rebrand(key, ins, uin).split("\f")
    body = "".join(f"<pre class='{'pb' if i < len(pages) - 2 else ''}'>{html.escape(p)}</pre>"
                   for i, p in enumerate(pages) if p.strip())
    open(base + ".html", "w", encoding="utf-8").write(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(WORDINGS[key]['title'])}</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>")
    if to_pdf(base + ".html", base + ".pdf"):
        return base + ".pdf", "pdf"
    return base + ".html", "html"
