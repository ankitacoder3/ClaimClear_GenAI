"""OCR settings and engine status.

The reader uses Tesseract through PyMuPDF for image-only pages (scans and photos).
Whether it runs is decided once, when the reader is built:

=============================  =========================================================
``CLAIMCLEAR_OCR``             ``auto`` (default: on when Tesseract is found), ``on``, ``off``
``CLAIMCLEAR_OCR_LANGUAGE``    Tesseract languages, e.g. ``eng`` (default) or ``eng+hin``
``CLAIMCLEAR_OCR_DPI``         render resolution for OCR, 150-600 (default 300)
``TESSDATA_PREFIX``            where Tesseract's language data is (optional, see below)
=============================  =========================================================

Tesseract's language data is found from ``TESSDATA_PREFIX``, then from Tesseract on the
PATH, then in the standard install folders: on Windows the per-user and machine-wide
``Tesseract-OCR/tessdata`` (the UB-Mannheim installer), on Linux ``/usr/share/tesseract``
(Fedora's ``tesseract`` package) and ``/usr/share/tesseract-ocr`` (Debian's), on macOS
Homebrew's ``share/tessdata``.

With OCR off or Tesseract missing, an image-only page comes back with
``ocr_status="unavailable"`` and a warning, never with guessed text.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pymupdf

ENGINE = "tesseract"
DEFAULT_LANGUAGE = "eng"
DEFAULT_DPI = 300
_LANGUAGE = re.compile(r"^[A-Za-z_]{3,20}(\+[A-Za-z_]{3,20}){0,4}$")


def _standard_tessdata() -> list[Path]:
    env = os.environ
    out = []
    if env.get("LOCALAPPDATA"):                              # winget / UB-Mannheim, per user
        out.append(Path(env["LOCALAPPDATA"]) / "Programs" / "Tesseract-OCR" / "tessdata")
    for key in ("ProgramFiles", "ProgramFiles(x86)"):        # UB-Mannheim, for all users
        if env.get(key):
            out.append(Path(env[key]) / "Tesseract-OCR" / "tessdata")
    out += [Path(p) for p in ("/usr/share/tesseract/tessdata",             # Fedora / RHEL: dnf install tesseract
                              "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
                              "/usr/share/tessdata", "/usr/local/share/tessdata", "/opt/homebrew/share/tessdata")]
    return out


def _tessdata() -> Optional[str]:
    """The folder holding Tesseract's ``*.traineddata`` files, or None when Tesseract isn't installed."""
    try:
        found = pymupdf.get_tessdata()        # TESSDATA_PREFIX, or tesseract on the PATH
    except Exception:  # noqa: BLE001 - any failure means: look in the standard folders
        found = None
    if found and Path(found).is_dir():
        return found
    for folder in _standard_tessdata():
        if folder.is_dir() and any(folder.glob("*.traineddata")):
            return str(folder)
    return None


def tessdata_dir() -> Optional[str]:
    return _tessdata()


def ocr_available() -> bool:
    """True when PyMuPDF can find Tesseract's language data."""
    return _tessdata() is not None


def installed_languages() -> list[str]:
    folder = _tessdata()
    if not folder:
        return []
    return sorted(p.stem for p in Path(folder).glob("*.traineddata"))


@dataclass(frozen=True)
class OcrSettings:
    enabled: bool
    language: str = DEFAULT_LANGUAGE
    dpi: int = DEFAULT_DPI

    def __post_init__(self) -> None:
        if not _LANGUAGE.match(self.language):
            raise ValueError(f"OCR language must look like 'eng' or 'eng+hin', not {self.language!r}")
        if not 150 <= self.dpi <= 600:
            raise ValueError(f"OCR dpi must be between 150 and 600, not {self.dpi}")

    @classmethod
    def resolve(cls, use_ocr: Optional[bool] = None, language: Optional[str] = None,
                dpi: Optional[int] = None) -> "OcrSettings":
        """Settings from the arguments, falling back to the environment, then the defaults."""
        if use_ocr is None:
            mode = os.environ.get("CLAIMCLEAR_OCR", "auto").strip().lower()
            if mode not in ("auto", "on", "off"):
                raise ValueError(f"CLAIMCLEAR_OCR must be auto, on or off, not {mode!r}")
            use_ocr = ocr_available() if mode == "auto" else mode == "on"
        language = language or os.environ.get("CLAIMCLEAR_OCR_LANGUAGE") or DEFAULT_LANGUAGE
        dpi = dpi or int(os.environ.get("CLAIMCLEAR_OCR_DPI") or DEFAULT_DPI)
        return cls(bool(use_ocr), language.strip(), dpi)

    def cache_key(self) -> str:
        return f"ocr:{self.language}:{self.dpi}" if self.enabled else "ocr:off"

    def status(self) -> dict:
        have = installed_languages()
        wanted = self.language.split("+")
        return {"engine": ENGINE, "installed": ocr_available(), "enabled": self.enabled,
                "language": self.language, "dpi": self.dpi, "installed_languages": have,
                "missing_languages": [lang for lang in wanted if lang not in have]}
