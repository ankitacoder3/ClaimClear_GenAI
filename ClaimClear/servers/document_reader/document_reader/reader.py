"""The document reader: checks a file, extracts it once, and serves later reads from a cache.

    reader = DocumentReader(cache_dir="var/case_store/text_cache")
    result = reader.read_file(path, "doc_3fa2c1d0e9b84a77", "application/pdf")
    result = reader.read_bytes(data, "image/png")            # document_id defaults to doc_<sha256[:16]>

Before extracting, the reader checks:

* the media type is one it reads (PDF, JPG, PNG): ``UNSUPPORTED_MEDIA_TYPE``;
* the file is no larger than ``MAX_BYTES``: ``DOCUMENT_TOO_LARGE``;
* the bytes really are that type (a renamed file is refused): ``MEDIA_TYPE_MISMATCH``.

**Cache.** OCR takes seconds a page, and agents read the same document more than
once, so results are cached under a key made of the file's SHA-256, the pages asked
for, the OCR settings and ``READER_VERSION``. A changed file, other pages, other OCR
settings or a new reader version all miss the cache. Results where OCR failed are not
cached, so a later read can try again. The cache holds extracted text, which is
personal data: keep it inside the case store, so it is deleted with the case.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from .extract import MAX_PAGES, ExtractionError, extract_document
from .ocr import OcrSettings

READER_VERSION = "1"          # bump whenever extraction output changes, so old cache entries are ignored
MAX_BYTES = 25 * 1024 * 1024
MEDIA_TYPES = ("application/pdf", "image/jpeg", "image/png")


def sniff_media_type(data: bytes) -> Optional[str]:
    """The media type the bytes actually are, from their first bytes; None if not one we read."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b"%PDF-" in data[:1024]:           # the PDF header may follow up to 1 KB of junk
        return "application/pdf"
    return None


def _pages_key(pages: Optional[Iterable[int]]) -> str:
    return ",".join(str(p) for p in sorted(set(pages))) if pages else "all"


class DocumentReader:
    """Reads PDFs, JPGs and PNGs into text with spans. Stateless apart from the optional cache."""

    def __init__(self, cache_dir: Optional[str | Path] = None, ocr: Optional[OcrSettings] = None,
                 use_ocr: Optional[bool] = None):
        self.ocr = ocr or OcrSettings.resolve(use_ocr)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------ reading

    def read_file(self, path: str | Path, document_id: str, media_type: str,
                  pages: Optional[Iterable[int]] = None) -> dict:
        path = Path(path)
        try:
            size = path.stat().st_size
        except OSError:
            raise ExtractionError("DOCUMENT_UNREADABLE", "the stored file could not be opened")
        self._check_size(size)
        return self.read_bytes(path.read_bytes(), media_type, pages, document_id)

    def read_bytes(self, data: bytes, media_type: str, pages: Optional[Iterable[int]] = None,
                   document_id: Optional[str] = None) -> dict:
        """Extract ``data`` and return the result as a dict in the ``DocumentTextOut`` shape."""
        if media_type not in MEDIA_TYPES:
            raise ExtractionError("UNSUPPORTED_MEDIA_TYPE", f"only PDF, JPG and PNG are read, not {media_type!r}")
        self._check_size(len(data))
        actual = sniff_media_type(data)
        if actual != media_type:
            raise ExtractionError("MEDIA_TYPE_MISMATCH",
                                  f"the file is declared {media_type} but its content is "
                                  f"{actual or 'not a PDF, JPG or PNG'}")
        digest = hashlib.sha256(data).hexdigest()
        document_id = document_id or f"doc_{digest[:16]}"
        key = hashlib.sha256(
            f"{READER_VERSION}|{digest}|{media_type}|{self.ocr.cache_key()}|{_pages_key(pages)}".encode()
        ).hexdigest()

        cached = self._load(key)
        if cached is not None:
            self.hits += 1
            return {**cached, "document_id": document_id}
        self.misses += 1
        # through JSON, so a fresh result and a cached one are identical (lists, not tuples)
        result = json.loads(json.dumps(extract_document(data, document_id, media_type, pages, ocr=self.ocr).to_dict()))
        if not any(p["ocr_status"] == "failed" for p in result["pages"]):
            self._store(key, result)
        return result

    def status(self) -> dict:
        return {"version": READER_VERSION, "media_types": list(MEDIA_TYPES), "max_bytes": MAX_BYTES,
                "max_pages": MAX_PAGES, "cache": self.cache_dir is not None, "ocr": self.ocr.status()}

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _check_size(size: int) -> None:
        if size > MAX_BYTES:
            raise ExtractionError("DOCUMENT_TOO_LARGE",
                                  f"the file is {size:,} bytes; the limit is {MAX_BYTES:,}")
        if size == 0:
            raise ExtractionError("DOCUMENT_UNREADABLE", "the file is empty")

    def _path(self, key: str) -> Path:
        assert self.cache_dir is not None
        return self.cache_dir / key[:2] / f"{key}.json"

    def _load(self, key: str) -> Optional[dict]:
        if self.cache_dir is None:
            return None
        try:
            return json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None                   # missing or damaged entry: extract again

    def _store(self, key: str, result: dict) -> None:
        if self.cache_dir is None:
            return
        target = self._path(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False)
            os.replace(tmp, target)
        except OSError:
            pass                          # a cache that can't be written only costs speed
