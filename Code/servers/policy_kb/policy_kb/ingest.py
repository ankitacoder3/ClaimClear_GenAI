"""Split a policy wording into clauses: one chunk per numbered clause, with metadata.

Two numbering layouts are recognised, and detected automatically:

* **Numbered sections**: ``4. COVERAGE``, clauses ``4.1``, ``4.3``, sub-clauses ``4.1.2``.
  Clause IDs are the printed numbers (``4.3``).
* **Lettered sections** (e.g. Go Digit's wording): ``C. BENEFITS COVERED UNDER THE
  POLICY`` with numbering that restarts in each section, the number often alone on its
  line and the title on the next (``1.`` / ``Hospitalization``), or inline
  (``10. Breach of law: (Code- Excl10)``). Clause IDs are section-qualified (``C.1``,
  ``C.1.1``, ``D.10``). Roman group labels (``I.`` / ``STANDARD EXCLUSIONS``) are dropped.

Both layouts may end with annexures (``Annexure I``, ``ANNEXURE A``, ``ANNEXURE - B``);
lists inside an annexure (``List I – Optional Items``) become their own chunks
(``Annexure A List I``).

**Lists inside clauses are numbered too** (the 19 listed illnesses, notes "1. 2. 3."), so a
number only starts a clause if it continues the numbering:

* a section number must be the next one and look like a heading;
* an inline clause number must be the next one in its section, and must not be followed later
  in the same section by a bare line with the same number (that bare line is the real clause,
  so the inline one is a list item such as "4. Mastoidectomy");
* a bare number line may skip one number, in case a clause was lost in extraction.

So "24 hours ...", "30 days ..." or "36 months prior ..." at the start of a line never become
clauses. Running page headers and footers and page numbers are removed first.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .models import Clause, WordingInfo

CLAUSE = re.compile(r"^\s*(?P<id>\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?P<rest>\S.*)$")
BARE_NUMBER = re.compile(r"^\s*(?P<id>\d{1,2}(?:\.\d{1,2}){0,3})\.\s*$")
SECTION_LETTER = re.compile(r"^\s*(?P<l>[A-Z])\.\s+(?P<rest>[A-Z][A-Z0-9 &,/()'’\-]{2,}?)\s*:?\s*$")
ROMAN_LABEL = re.compile(r"^\s*(?P<r>[IVX]{1,4})\.\s*(?P<rest>.*?)\s*$")
ANNEXURE = re.compile(r"^\s*(?P<word>annexure|appendix|schedule)\s*[-–:]?\s*(?P<num>[ivxlc]+|\d+|[a-z])\b\s*[-–:.]?\s*"
                      r"(?P<rest>.*)$", re.I)
ANNEX_LIST = re.compile(r"^\s*list\s+(?P<r>[ivx]+)\b\s*[-–:]?\s*(?P<rest>.*)$", re.I)
PAGE_LINE = re.compile(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", re.I)
CODE = re.compile(r"\b(?:code\s*[-:]?\s*)?(Excl\d{2})\b", re.I)
LIST_MARK = re.compile(r"^\s*(?:[ivxlc]+[.)]|[a-z][.)]|\(\w{1,4}\)|[•\-–])\s+", re.I)
DEFINITION = re.compile(r"(means|shall mean|refers to|\bis an?\b|is defined as|:)", re.I)


@dataclass
class IngestResult:
    info: WordingInfo
    clauses: list[Clause]
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Draft:
    clause_id: str
    first: str
    lines: list[str]
    page_start: Optional[int]
    page_end: Optional[int]
    needs_title: bool = False
    parent: Optional[str] = None
    line_pages: list = field(default_factory=list)


def _upper_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(c.isupper() for c in letters) / max(len(letters), 1)


def _looks_like_heading(rest: str) -> bool:
    """Short, no full stop at the end, mostly upper-case or title-case."""
    rest = rest.strip()
    if not rest or len(rest) > 90 or rest.endswith((".", ";", ",")):
        return False
    return _upper_ratio(rest) >= 0.6 or rest[:1].isupper()


def _clean_lines(pages: list[list[str]]) -> list[tuple[Optional[int], str]]:
    """Drop page numbers and running headers/footers (lines on at least half the pages)."""
    numbered = len(pages) > 1
    counts = Counter(" ".join(line.split()) for page in pages for line in set(page) if line.strip())
    repeated = {line for line, n in counts.items() if numbered and n >= max(2, len(pages) // 2)}
    out = []
    for i, page in enumerate(pages, start=1):
        for line in page:
            s = " ".join(line.split())
            if not s or PAGE_LINE.match(s) or s in repeated:
                continue
            out.append((i if numbered else None, s))
    return out


def _is_section_header(line: str, expected: str) -> Optional[re.Match]:
    m = SECTION_LETTER.match(line)
    return m if m and m.group("l") == expected and _upper_ratio(m.group("rest")) >= 0.9 else None


def _later_bare_numbers(lines: list[tuple[Optional[int], str]]) -> list[frozenset[str]]:
    """For each line, the bare clause numbers that appear later in the same lettered section."""
    out: list[frozenset[str]] = [frozenset()] * len(lines)
    seen: set[str] = set()
    for i in range(len(lines) - 1, -1, -1):
        out[i] = frozenset(seen)
        line = lines[i][1]
        if SECTION_LETTER.match(line) or ANNEXURE.match(line):
            seen = set()                       # a section boundary: numbering restarts above it
            continue
        m = BARE_NUMBER.match(line)
        if m:
            seen.add(m.group("id"))
    return out


def split_clauses(lines: list[tuple[Optional[int], str]]) -> tuple[list[_Draft], list[str]]:
    drafts: list[_Draft] = []
    warnings: list[str] = []
    lettered = sum(1 for _, s in lines if SECTION_LETTER.match(s) and _upper_ratio(s) >= 0.9) >= 3
    later_bare = _later_bare_numbers(lines) if lettered else [frozenset()] * len(lines)

    letter: Optional[str] = None       # current section letter (lettered layout)
    top = 0                            # last top-level clause number in the current section
    seen: set[str] = set()
    current: Optional[_Draft] = None
    annexure: Optional[str] = None
    drop_label = False
    preamble = 0

    def start(cid: str, first: str, page, needs_title=False, parent=None) -> None:
        nonlocal current
        current = _Draft(cid, first, [], page, page, needs_title, parent)
        seen.add(cid)
        drafts.append(current)

    def qualify(num: str) -> str:
        return f"{letter}.{num}" if letter else num

    for i, (page, line) in enumerate(lines):
        if current is not None and current.needs_title:
            current.first, current.needs_title = line, False
            current.page_end = page
            continue
        if drop_label:
            drop_label = False
            if _upper_ratio(line) >= 0.9 and len(line) <= 90:
                continue                                          # roman group label, e.g. STANDARD EXCLUSIONS

        if annexure is None:
            # lettered section header: next letter, all caps
            if lettered:
                expected = "A" if letter is None else chr(ord(letter) + 1)
                m = _is_section_header(line, expected)
                if m:
                    letter, top = m.group("l"), 0
                    start(letter, m.group("rest").strip(), page)
                    continue
                r = ROMAN_LABEL.match(line)
                if r and (not r.group("rest") or (_upper_ratio(r.group("rest")) >= 0.9 and len(r.group("rest")) <= 90)):
                    drop_label = not r.group("rest")
                    continue
            a = ANNEXURE.match(line)
            if a and (current is None or a.group("rest") == "" or _looks_like_heading(a.group("rest"))
                      or _upper_ratio(line) >= 0.6):
                annexure = f"{a.group('word').title()} {a.group('num').upper()}"
                if annexure not in seen:
                    start(annexure, a.group("rest") or annexure, page)
                    continue
                annexure = None
            b = BARE_NUMBER.match(line)
            c = CLAUSE.match(line) if not b else None
            num = (b or c).group("id") if (b or c) else None
            if num is not None:
                parts = [int(p) for p in num.split(".")]
                cid = qualify(num)
                ok = False
                if cid not in seen:
                    if len(parts) > 1:
                        ok = parts[0] == top
                    elif b:
                        ok = top < parts[0] <= top + 2
                    elif lettered:
                        ok = parts[0] == top + 1 and num not in later_bare[i] and (
                            DEFINITION.search(c.group("rest")[:80]) is not None or _looks_like_heading(c.group("rest"))
                            or len(c.group("rest")) > 20)
                    else:   # a numbered section heading: next number, upper-case heading ("4. COVERAGE")
                        ok = parts[0] == top + 1 and _looks_like_heading(c.group("rest")) \
                            and _upper_ratio(c.group("rest")) >= 0.6
                if ok:
                    if len(parts) == 1:
                        top = parts[0]
                    start(cid, "" if b else c.group("rest"), page, needs_title=bool(b))
                    continue
        else:
            al = ANNEX_LIST.match(line)
            if al:
                cid = f"{annexure} List {al.group('r').upper()}"
                if cid not in seen:
                    start(cid, al.group("rest") or cid, page, parent=annexure)
                    continue
            a = ANNEXURE.match(line)
            if a and _upper_ratio(line) >= 0.6:
                cid = f"{a.group('word').title()} {a.group('num').upper()}"
                if cid not in seen:
                    annexure = cid
                    start(cid, a.group("rest") or cid, page)
                    continue

        if current is None:
            preamble += 1
        else:
            current.lines.append(line)
            current.line_pages.append(page)
            current.page_end = page

    if not drafts:
        warnings.append("no numbered clauses found")
    if preamble:
        warnings.append(f"{preamble} line(s) before the first clause were not indexed (title page, UIN, notes)")
    if lettered:
        warnings.append("lettered-section layout detected: clause IDs are section-qualified, e.g. C.1, D.3")
    return drafts, warnings


LONG_CLAUSE = 3000   # characters; longer clauses are split at an internal 1., 2., 3. list


def _split_long(drafts: list[_Draft]) -> list[_Draft]:
    """Split very long clauses at an internal numbered list that runs 1, 2, 3, ... in order.

    Go Digit's E.28 "Claim Procedure" (7,500 characters) holds cashless, reimbursement,
    notification, documents, co-payment and settlement sections numbered 1-n; they become
    E.28.1 ... E.28.n so each can be found and cited on its own. Short clauses are never
    split, so lists such as the 19 listed illnesses stay inside their clause.
    """
    out: list[_Draft] = []
    for d in drafts:
        if _is_annexure(d.clause_id) or sum(len(x) for x in d.lines) <= LONG_CLAUSE:
            out.append(d)
            continue
        starts, expected = [], 1
        for i, line in enumerate(d.lines):
            m = CLAUSE.match(line)
            if m and "." not in m.group("id") and int(m.group("id")) == expected:
                starts.append((i, m.group("rest")))
                expected += 1
        if len(starts) < 3:
            out.append(d)
            continue
        pages = d.line_pages or [d.page_start] * len(d.lines)
        head = _Draft(d.clause_id, d.first, d.lines[:starts[0][0]], d.page_start,
                      pages[starts[0][0] - 1] if starts[0][0] else d.page_start, parent=d.parent,
                      line_pages=pages[:starts[0][0]])
        out.append(head)
        for n, (i, rest) in enumerate(starts, start=1):
            j = starts[n][0] if n < len(starts) else len(d.lines)
            out.append(_Draft(f"{d.clause_id}.{n}", rest, d.lines[i + 1:j], pages[i], pages[j - 1],
                              line_pages=pages[i + 1:j]))
    return out


def _split_title(first: str, body: list[str]) -> tuple[str, str]:
    """Title and text of a clause from its first line and the lines after it."""
    first = first.strip()
    # "Accident means ...", "Migrationmeans ..." (missing space in the PDF), "An AYUSH Hospital is a ..."
    m = re.match(r"^(?P<t>[^.:]{2,80}?)(\s*means|\s+shall mean|\s+refers to|\s+is defined as|\s+is an?)\b", first, re.I)
    if m:
        return m.group("t").strip(), _join([first] + body)
    m = re.match(r"^(?P<t>[^:]{2,70}):\s*(?P<rest>.*)$", first)
    if m:
        rest = m.group("rest").strip()
        return m.group("t").strip(), _join(([rest] if rest else []) + body)
    if _looks_like_heading(first) and body:
        return first, _join(body)
    title = " ".join(first.split()[:8]).rstrip(".,;:")
    return title, _join([first] + body)


def _join(lines: Iterable[str]) -> str:
    """Join wrapped lines into paragraphs; keep list items on their own lines."""
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out and not LIST_MARK.match(line) and not out[-1].endswith((":",)):
            out[-1] = out[-1][:-1] + line if out[-1].endswith("-") else out[-1] + " " + line
        else:
            out.append(line)
    return "\n".join(out).strip()


def _is_annexure(cid: str) -> bool:
    return cid.lower().startswith(("annexure", "appendix", "schedule"))


def _build(drafts: list[_Draft]) -> list[Clause]:
    titles: dict[str, str] = {}
    clauses = []
    for d in drafts:
        title, text = _split_title(d.first, d.lines)
        is_root = d.parent is None and "." not in d.clause_id     # "4", "C", "Annexure A"
        if is_root and not d.lines and _looks_like_heading(d.first):
            title, text = d.first.strip(), ""                        # a heading with no text of its own
        titles[d.clause_id] = title
        if d.parent:
            parent = d.parent
        elif _is_annexure(d.clause_id) or "." not in d.clause_id:
            parent = None
        else:
            parent = d.clause_id.rsplit(".", 1)[0]
        root = d.parent or (d.clause_id if parent is None else d.clause_id.split(".")[0])
        section = titles.get(root, title)
        codes = tuple(dict.fromkeys(c.capitalize() for c in CODE.findall(f"{title} {text}")))
        clauses.append(Clause(d.clause_id, title, text, section, parent, d.page_start, d.page_end, codes))
    return clauses


def ingest_lines(pages: list[list[str]], info: WordingInfo) -> IngestResult:
    drafts, warnings = split_clauses(_clean_lines(pages))
    clauses = _build(_split_long(drafts))
    empty = [c.clause_id for c in clauses if not c.text and not any(x.parent_id == c.clause_id for x in clauses)]
    if empty:
        warnings.append(f"clauses with no text: {', '.join(empty)}")
    return IngestResult(info, clauses, warnings)


def ingest_text(text: str, info: WordingInfo) -> IngestResult:
    """Plain text. Form feeds (\\f) separate pages if present."""
    pages = [p.splitlines() for p in text.split("\f")]
    return ingest_lines(pages, info)


def ingest_pdf(path: str | Path, info: WordingInfo) -> IngestResult:
    """A text-based PDF, with page numbers on every clause. Needs PyMuPDF."""
    import pymupdf

    with pymupdf.open(path) as doc:
        pages = [page.get_text("text").splitlines() for page in doc]
    result = ingest_lines(pages, info)
    if sum(len(p) for p in pages) == 0:
        result.warnings.append("the PDF has no text layer (a scan?); OCR it first")
    return result


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_file(path: str | Path, info: WordingInfo) -> IngestResult:
    """A ``.pdf`` or ``.txt`` wording. Fills ``info.sha256`` from the file."""
    path = Path(path)
    info = WordingInfo(**{**info.to_dict(), "sha256": info.sha256 or file_sha256(path)})
    if path.suffix.lower() == ".pdf":
        return ingest_pdf(path, info)
    return ingest_text(path.read_text(encoding="utf-8"), info)
