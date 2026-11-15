"""Text extraction with source spans, and a clear line between what a reader sees and what is hidden.

For every page the extractor returns:

* ``spans``: each piece of text with its bounding box, size and colour, and
  ``hidden`` / ``hidden_reasons`` when a person looking at the page could not see it;
* ``text``: the **visible** text only, in reading order (what the document reader should use);
* ``hidden_text``: everything hidden, kept apart so the input guardrails can inspect it
  and nothing downstream treats it as part of the document.

It also returns the other places documents carry text a reader doesn't see on
the page: PDF metadata, annotations (sticky notes), form fields and attached
files. All of it is **untrusted data**; none of it is an instruction.

Hidden-text rules (``hidden_reasons``):

    invisible_render   text drawn in invisible render mode (PDF Tr 3)
    transparent        text drawn with zero opacity
    tiny_font          font size under 2 pt
    white_on_white     white text with no coloured shape or image behind it
    covered            an opaque shape drawn after the text covers most of it
    off_page           outside the visible page area

White text on a coloured header bar is visible and is not flagged.

Image-only pages (scans, photos) need OCR (settings in ``ocr.py``). With
Tesseract installed, OCR words become the page's spans (``source="ocr"``) and any
invisible text layer is cross-checked against them. Without it,
``ocr_status="unavailable"`` and a warning says the page could not be read.

Input is a PDF, JPG or PNG, given as a path or as bytes.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import pymupdf

from .ocr import OcrSettings, ocr_available, tessdata_dir

__all__ = ["DocumentText", "ExtractionError", "MAX_PAGES", "OcrSettings", "extract_document", "ocr_available"]

FILETYPES = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}
MAX_PAGES = 50
MAX_SPANS_PER_PAGE = 5000
TEXT_CAP = 1000
ATTACHMENT_PREVIEW = 2000


class ExtractionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- output shapes


@dataclass
class Span:
    span_id: str
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    color: str
    hidden: bool
    hidden_reasons: list[str]


@dataclass
class Page:
    page: int
    width: float
    height: float
    source: str           # "text_layer", "ocr" or "none"
    text: str             # visible text, reading order
    hidden_text: str
    spans: list[Span]
    has_images: bool
    ocr_status: str       # "not_needed", "done", "unavailable", "failed"
    warnings: list[str] = field(default_factory=list)


@dataclass
class Annotation:
    page: int
    type: str
    author: str
    content: str
    bbox: tuple[float, float, float, float]


@dataclass
class FormField:
    page: int
    name: str
    value: str
    field_type: str
    hidden: bool
    bbox: tuple[float, float, float, float]


@dataclass
class Attachment:
    name: str
    size_bytes: int
    description: str
    text_preview: str


@dataclass
class DocumentText:
    document_id: str
    media_type: str
    page_count: int
    pages_returned: list[int]
    metadata: dict[str, str]
    pdf_flags: list[str]
    pages: list[Page]
    annotations: list[Annotation]
    form_fields: list[FormField]
    attachments: list[Attachment]
    warnings: list[str]
    untrusted_content: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- helpers


def _rgb(color) -> tuple[float, float, float]:
    if color is None:
        return (0.0, 0.0, 0.0)
    c = tuple(float(v) for v in color)
    if len(c) == 1:
        return (c[0], c[0], c[0])
    if len(c) == 4:  # CMYK
        k = c[3]
        return tuple((1 - min(1.0, v + k)) for v in c[:3])  # type: ignore[return-value]
    return c[:3]  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in rgb)


def _near_white(rgb: tuple[float, float, float]) -> bool:
    return all(v >= 0.92 for v in rgb)


def _box(rect) -> tuple[float, float, float, float]:
    return tuple(round(float(v), 1) for v in rect)  # type: ignore[return-value]


def _cap(text: str, limit: int = TEXT_CAP) -> str:
    text = (text or "").replace("\x00", "")
    return text if len(text) <= limit else text[:limit] + "…"


def _area(r: pymupdf.Rect) -> float:
    return max(0.0, r.width) * max(0.0, r.height)


# --------------------------------------------------------------------------- page analysis


@dataclass
class _Raw:
    text: str
    rect: pymupdf.Rect
    size: float
    rgb: tuple[float, float, float]
    reasons: list[str]


def _trace_spans(page: pymupdf.Page) -> list[_Raw]:
    fills = []
    for d in page.get_drawings():
        if d.get("fill") is None or (d.get("fill_opacity") or 1) < 0.9:
            continue
        fills.append((d.get("seqno", -1), pymupdf.Rect(d["rect"]), _rgb(d["fill"])))
    images = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    page_rect = page.rect
    out = []
    for s in page.get_texttrace()[:MAX_SPANS_PER_PAGE]:
        text = "".join(chr(c[0]) for c in s["chars"])
        if not text.strip():
            continue
        rect = pymupdf.Rect(s["bbox"])
        rgb = _rgb(s.get("color"))
        size = float(s.get("size") or 0)
        seq = s.get("seqno", -1)
        reasons = []
        if s.get("type") == 3:
            reasons.append("invisible_render")
        if (s.get("opacity") if s.get("opacity") is not None else 1) <= 0.01:
            reasons.append("transparent")
        if size < 2:
            reasons.append("tiny_font")
        inside = rect & page_rect
        if rect.is_empty or _area(inside) < 0.5 * max(_area(rect), 1e-6):
            reasons.append("off_page")
        if _near_white(rgb) and "invisible_render" not in reasons:
            centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            behind = any(fseq < seq and frect.contains(centre) and not _near_white(frgb) for fseq, frect, frgb in fills)
            on_image = any(img.contains(centre) for img in images)
            if not behind and not on_image:
                reasons.append("white_on_white")
        if _area(rect) > 0:
            for fseq, frect, frgb in fills:
                if fseq > seq and _area(frect & rect) >= 0.8 * _area(rect):
                    reasons.append("covered")
                    break
        out.append(_Raw(text, rect, size, rgb, reasons))
    return out


def _reading_order(raws: list[_Raw]) -> list[_Raw]:
    """Sort into lines (top to bottom), then left to right."""
    items = sorted(raws, key=lambda r: ((r.rect.y0 + r.rect.y1) / 2, r.rect.x0))
    lines: list[list[_Raw]] = []
    line_y = None
    for r in items:
        y = (r.rect.y0 + r.rect.y1) / 2
        if line_y is None or abs(y - line_y) > max(2.0, 0.5 * max(r.size, 1)):
            lines.append([r])
            line_y = y
        else:
            lines[-1].append(r)
    ordered = []
    for line in lines:
        ordered.extend(sorted(line, key=lambda r: r.rect.x0))
    return ordered


def _join(raws: list[_Raw]) -> str:
    out = []
    prev: Optional[_Raw] = None
    for r in raws:
        if prev is not None:
            same_line = abs((r.rect.y0 + r.rect.y1) / 2 - (prev.rect.y0 + prev.rect.y1) / 2) <= max(2.0, 0.5 * max(r.size, 1))
            if not same_line:
                out.append("\n")
            elif r.rect.x0 - prev.rect.x1 > 0.25 * max(r.size, 1):
                out.append(" ")
        out.append(r.text)
        prev = r
    return re.sub(r"[ \t]+\n", "\n", "".join(out)).strip()


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text)}


def _ocr_spans(page: pymupdf.Page, ocr: OcrSettings) -> list[_Raw]:
    tp = page.get_textpage_ocr(dpi=ocr.dpi, full=True, language=ocr.language, tessdata=tessdata_dir())
    words = page.get_text("words", textpage=tp)
    return [_Raw(w[4], pymupdf.Rect(w[:4]), max(1.0, (w[3] - w[1]) * 0.8), (0.0, 0.0, 0.0), []) for w in words]


def _page(page: pymupdf.Page, number: int, ocr: OcrSettings) -> Page:
    raws = _trace_spans(page)
    images = page.get_image_info()
    image_cover = sum(_area(pymupdf.Rect(i["bbox"]) & page.rect) for i in images) / max(_area(page.rect), 1)
    visible = [r for r in raws if not r.reasons]
    hidden = [r for r in raws if r.reasons]
    warnings: list[str] = []
    source, ocr_status = ("text_layer" if visible else "none"), "not_needed"

    needs_ocr = not visible and image_cover >= 0.5
    if needs_ocr:
        if not ocr.enabled:
            ocr_status = "unavailable"
            warnings.append("This page is an image and OCR is not available, so its text could not be read.")
            if any("invisible_render" in r.reasons for r in hidden):
                warnings.append("The page carries an invisible text layer that could not be checked against the "
                                "image; it is returned only as hidden text.")
        else:
            try:
                words = _ocr_spans(page, ocr)
                visible, source, ocr_status = words, "ocr", "done"
                layer = _numbers(" ".join(r.text for r in hidden if "invisible_render" in r.reasons))
                seen = _numbers(" ".join(r.text for r in words))
                missing = sorted(layer - seen)
                if missing:
                    warnings.append("The invisible text layer disagrees with the image: numbers in the layer but "
                                    f"not in the picture: {', '.join(missing[:20])}.")
            except Exception as exc:  # noqa: BLE001
                ocr_status = "failed"
                warnings.append(f"OCR failed on this page: {type(exc).__name__}.")

    ordered_visible = _reading_order(visible)
    ordered_hidden = _reading_order(hidden)
    spans = [
        Span(f"p{number}-s{i}", _cap(r.text), _box(r.rect), round(r.size, 1), _hex(r.rgb), bool(r.reasons),
             list(dict.fromkeys(r.reasons)))
        for i, r in enumerate(ordered_visible + ordered_hidden, start=1)
    ]
    if hidden:
        kinds = sorted({k for r in hidden for k in r.reasons})
        warnings.append(f"{len(hidden)} piece(s) of hidden text ({', '.join(kinds)}); returned in hidden_text, "
                        "not in text.")
    return Page(number, round(page.rect.width, 1), round(page.rect.height, 1), source, _join(ordered_visible),
                _join(ordered_hidden), spans, bool(images), ocr_status, warnings)


# --------------------------------------------------------------------------- document


def _metadata(doc: pymupdf.Document) -> dict[str, str]:
    keep = ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")
    return {k: _cap(str(v)) for k, v in (doc.metadata or {}).items() if k in keep and v}


def _pdf_flags(data: bytes, doc: pymupdf.Document) -> list[str]:
    flags = []
    if doc.is_pdf:
        if data.count(b"%%EOF") > 1:
            flags.append("incremental_update")
        meta = doc.metadata or {}
        if meta.get("modDate") and meta.get("creationDate") and meta["modDate"] != meta["creationDate"]:
            flags.append("modified_after_creation")
    return flags


def _attachments(doc: pymupdf.Document) -> list[Attachment]:
    out = []
    if not doc.is_pdf:
        return out
    for name in doc.embfile_names():
        info = doc.embfile_info(name)
        data = doc.embfile_get(name)[:ATTACHMENT_PREVIEW * 4]
        text = data.decode("utf-8", errors="replace")
        printable = sum(ch.isprintable() or ch in "\n\r\t" for ch in text) / max(len(text), 1)
        preview = _cap(text, ATTACHMENT_PREVIEW) if printable > 0.9 else ""
        out.append(Attachment(_cap(name, 200), int(info.get("size") or info.get("length") or len(data)),
                              _cap(info.get("desc") or "", 500), preview))
    return out


def extract_document(source: str | Path | bytes, document_id: str, media_type: str,
                     pages: Optional[Iterable[int]] = None, use_ocr: Optional[bool] = None,
                     ocr: Optional[OcrSettings] = None) -> DocumentText:
    """Extract one document, given as a path or as bytes. ``pages`` are 1-based; default all (up to ``MAX_PAGES``).

    OCR: pass ``ocr`` settings, or ``use_ocr`` to switch it on or off; with neither, the
    environment decides (``CLAIMCLEAR_OCR``, default: on when Tesseract is installed).
    """
    if ocr is None:
        ocr = OcrSettings.resolve(use_ocr)
    try:
        data = source if isinstance(source, bytes) else Path(source).read_bytes()
        doc = pymupdf.open(stream=data, filetype=FILETYPES.get(media_type))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("DOCUMENT_UNREADABLE", f"could not open the document ({type(exc).__name__})")
    with doc:
        if doc.needs_pass:
            raise ExtractionError("DOCUMENT_ENCRYPTED", "the document is password-protected")
        total = doc.page_count
        wanted = sorted(set(pages)) if pages else list(range(1, total + 1))
        bad = [p for p in wanted if p < 1 or p > total]
        if bad:
            raise ExtractionError("PAGE_OUT_OF_RANGE", f"pages {bad} are outside 1-{total}")
        warnings = []
        if len(wanted) > MAX_PAGES:
            warnings.append(f"Only the first {MAX_PAGES} requested pages are returned.")
            wanted = wanted[:MAX_PAGES]
        out_pages = [_page(doc[p - 1], p, ocr) for p in wanted]
        annotations, fields = [], []
        for p in wanted:
            page = doc[p - 1]
            for a in page.annots() or []:
                if a.type[1] == "Widget":
                    continue
                info = a.info or {}
                annotations.append(Annotation(p, a.type[1], _cap(info.get("title", ""), 200),
                                              _cap(info.get("content", "")), _box(a.rect)))
            for w in page.widgets() or []:
                fields.append(FormField(p, _cap(w.field_name or "", 200), _cap(str(w.field_value or "")),
                                        w.field_type_string or "", w.field_display in (1, 3), _box(w.rect)))
        attachments = _attachments(doc)
        if annotations:
            warnings.append(f"{len(annotations)} annotation(s) carry text that is not part of the printed page.")
        if any(f.hidden for f in fields):
            warnings.append("A hidden form field carries text a reader cannot see.")
        if attachments:
            warnings.append(f"{len(attachments)} attached file(s) are embedded in the document.")
        return DocumentText(document_id, media_type, total, wanted, _metadata(doc), _pdf_flags(data, doc),
                            out_pages, annotations, fields, attachments, warnings)
