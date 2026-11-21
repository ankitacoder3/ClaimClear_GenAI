"""The policy catalogue: every wording policy-kb can serve, and the per-case uploaded wordings.

Two sources, one way in (``PolicyLibrary.resolve``):

* **Catalogue** wordings, reviewed and pre-indexed, listed in ``development/dev_data/wordings/catalogue.json``::

      {"default": "GODHLIP24179V022324",
       "wordings": [{"wording_uin": "GODHLIP24179V022324", "insurer": "...", "product": "...",
                     "version": "...", "index": "index.json", "reviewed": true}]}

  ``index`` is relative to the index folder (``var/policy_kb``). Without a catalogue file the
  library serves the single default index (``$CLAIMCLEAR_POLICY_KB_INDEX``), as before.

* **Uploaded** wordings: a policy the user uploads because theirs is not in the catalogue. The app
  indexes its visible text with ``register_upload`` into ``var/policy_kb/uploads/<case_id>/<doc_id>.json``
  as ``wording_uin = "upload:<doc_id>"``. It is served only to calls that name the owning ``case_id``,
  is never reviewed (no rule map), and is deleted with the case.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .ingest import ingest_lines
from .kb import PolicyKB
from .models import Clause, WordingInfo
from .tools import PolicyKBError

CATALOGUE_ENV = "CLAIMCLEAR_POLICY_CATALOGUE"
UPLOAD_EMBEDDER_ENV = "CLAIMCLEAR_UPLOAD_EMBEDDER"     # "hashing" (default, offline) or "openrouter"
UIN = re.compile(r"^[A-Z]{7}\d{5}V\d{6}$")
UPLOAD_UIN = re.compile(r"^upload:(doc_[0-9a-f]{16})$")
UIN_IN_TEXT = re.compile(r"\b[A-Z]{7}\d{5}V\d{6}\b")
CASE_ID = re.compile(r"^case_[0-9a-f]{16}$")
MIN_CLAUSES = 20            # fewer clauses than this: the layout wasn't recognised; index page by page
MAX_PAGES = 300
MAX_PAGE_CHARS = 20_000


def default_catalogue_path() -> Path:
    env = os.environ.get(CATALOGUE_ENV)
    return Path(env) if env else Path(__file__).resolve().parents[3] / "development" / "dev_data" / "wordings" / "catalogue.json"


@dataclass(frozen=True)
class Entry:
    wording_uin: str
    insurer: str
    product: str
    version: str
    index: Path
    reviewed: bool
    source: str = "catalogue"          # or "uploaded"

    def summary(self, kb: Optional[PolicyKB]) -> dict:
        return {"wording_uin": self.wording_uin, "insurer": self.insurer, "product": self.product,
                "version": self.version, "source": self.source, "reviewed": self.reviewed,
                "index_available": kb is not None, "clause_count": len(kb.clauses) if kb else None,
                "has_rule_map": bool(kb and kb.rule_map().get("rules"))}


class _Holder:
    """Loads one index on first use and again whenever the file changes."""

    def __init__(self, path: Path, loader: Callable[[Path], PolicyKB]):
        self.path = path
        self._loader = loader
        self._kb: Optional[PolicyKB] = None
        self._mtime: Optional[float] = None
        self._lock = threading.Lock()

    def get(self) -> PolicyKB:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                if self._kb is not None:
                    return self._kb
                raise PolicyKBError("INDEX_UNAVAILABLE", f"no policy-kb index at {self.path}; build it with: "
                                                         "python -m policy_kb build --wording <wording.pdf>")
            if self._kb is None or mtime != self._mtime:
                try:
                    self._kb = self._loader(self.path)
                except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
                    raise PolicyKBError("INDEX_UNAVAILABLE", f"the policy-kb index could not be loaded: {exc}")
                self._mtime = mtime
            return self._kb

    def peek(self) -> Optional[PolicyKB]:
        try:
            return self.get()
        except PolicyKBError:
            return None


class PolicyLibrary:
    """Every wording the server can serve, routed by ``wording_uin``."""

    def __init__(self, entries: list[Entry], default_uin: str, index_root: Path,
                 loader: Callable[[Path], PolicyKB], fixed: Optional[dict[str, PolicyKB]] = None):
        self.entries = {e.wording_uin: e for e in entries}
        self.default_uin = default_uin
        self.index_root = index_root
        self.uploads_root = index_root / "uploads"
        self._loader = loader
        self._fixed = dict(fixed or {})
        self._holders: dict[Path, _Holder] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_kb(cls, kb: PolicyKB, index_root: Path, loader: Callable[[Path], PolicyKB]) -> "PolicyLibrary":
        """One in-memory wording (tests)."""
        uin = kb.info.uin or "default"
        entry = Entry(uin, kb.info.insurer, kb.info.product, kb.info.version, Path("memory"),
                      reviewed=bool(kb.rule_map().get("rules")))
        return cls([entry], uin, index_root, loader, fixed={uin: kb})

    @classmethod
    def from_index(cls, index_path: Path, loader: Callable[[Path], PolicyKB]) -> "PolicyLibrary":
        """One index file, its wording learned when it is first loaded."""
        lib = cls([], "", index_path.parent, loader)
        lib._single = index_path               # resolved lazily: the index may not exist yet
        return lib

    @classmethod
    def from_catalogue(cls, catalogue_path: Path, index_root: Path,
                       loader: Callable[[Path], PolicyKB]) -> "PolicyLibrary":
        raw = json.loads(catalogue_path.read_text(encoding="utf-8"))
        entries = []
        for w in raw.get("wordings", []):
            if not UIN.match(w.get("wording_uin", "")):
                raise ValueError(f"catalogue entry has no valid wording_uin: {w}")
            entries.append(Entry(w["wording_uin"], w.get("insurer", ""), w.get("product", ""), w.get("version", ""),
                                 index_root / w.get("index", f"{w['wording_uin']}/index.json"),
                                 bool(w.get("reviewed", False))))
        default = raw.get("default") or (entries[0].wording_uin if entries else "")
        return cls(entries, default, index_root, loader)

    # ------------------------------------------------------------------ resolution

    def _holder(self, path: Path) -> _Holder:
        with self._lock:
            if path not in self._holders:
                self._holders[path] = _Holder(path, self._loader)
            return self._holders[path]

    def _single_kb(self) -> Optional[PolicyKB]:
        single = getattr(self, "_single", None)
        return self._holder(single).get() if single else None

    def resolve(self, wording_uin: Optional[str] = None, case_id: Optional[str] = None) -> PolicyKB:
        """The index for ``wording_uin`` (default: the catalogue's default wording)."""
        single = getattr(self, "_single", None)
        if single is not None and not (wording_uin or "").startswith("upload:"):
            kb = self._holder(single).get()
            if wording_uin and wording_uin not in (kb.info.uin, kb.info.key):
                raise PolicyKBError("UNKNOWN_WORDING", f"this server only has wording {kb.info.key!r}")
            return kb
        uin = wording_uin or self.default_uin
        m = UPLOAD_UIN.match(uin or "")
        if m:
            if not case_id or not CASE_ID.match(case_id):
                raise PolicyKBError("UNKNOWN_WORDING", f"{uin} is an uploaded wording: pass the case_id that owns it")
            path = self.uploads_root / case_id / f"{m.group(1)}.json"
            if not path.exists():
                raise PolicyKBError("UNKNOWN_WORDING", f"case {case_id} has no indexed upload {m.group(1)}")
            return self._holder(path).get()
        if uin in self._fixed:
            return self._fixed[uin]
        entry = self.entries.get(uin)
        if entry is None:
            known = ", ".join(sorted(self.entries)) or "none"
            raise PolicyKBError("UNKNOWN_WORDING", f"wording {uin!r} is not in the catalogue (known: {known})")
        return self._holder(entry.index).get()

    def is_reviewed(self, kb: PolicyKB) -> bool:
        if kb.info.uin.startswith("upload:"):
            return False
        entry = self.entries.get(kb.info.uin)
        return entry.reviewed if entry else bool(kb.rule_map().get("rules"))

    # ------------------------------------------------------------------ listing

    def list(self, insurer: Optional[str] = None, query: Optional[str] = None,
             case_id: Optional[str] = None) -> dict:
        rows = []
        single = getattr(self, "_single", None)
        if single is not None:
            kb = self._holder(single).peek()
            if kb is not None:
                e = Entry(kb.info.uin or kb.info.key, kb.info.insurer, kb.info.product, kb.info.version, single,
                          bool(kb.rule_map().get("rules")))
                rows.append(e.summary(kb))
        for uin, e in sorted(self.entries.items()):
            kb = self._fixed.get(uin) or self._holder(e.index).peek()
            rows.append(e.summary(kb))
        if case_id and CASE_ID.match(case_id):
            for path in sorted((self.uploads_root / case_id).glob("doc_*.json")):
                kb = self._holder(path).peek()
                if kb is not None:
                    rows.append(Entry(kb.info.uin, kb.info.insurer, kb.info.product, kb.info.version, path,
                                      False, "uploaded").summary(kb))
        if insurer:
            rows = [r for r in rows if insurer.lower() in r["insurer"].lower()]
        if query:
            q = query.lower()
            rows = [r for r in rows if q in " ".join(str(r[k]) for k in ("insurer", "product", "wording_uin",
                                                                          "version")).lower()]
        default = self.default_uin or (rows[0]["wording_uin"] if rows and single is not None else "")
        return {"default_wording_uin": default, "policies": rows}

    # ------------------------------------------------------------------ uploads

    def register_upload(self, case_id: str, document_id: str, pages: list[dict],
                        embedder: Optional[str] = None) -> dict:
        """Index the visible text of an uploaded policy for one case. Returns a summary for the app."""
        if not CASE_ID.match(case_id or "") or not re.match(r"^doc_[0-9a-f]{16}$", document_id or ""):
            raise PolicyKBError("UPLOAD_REJECTED", "case_id or document_id is not a valid ID")
        texts = [(int(p["page"]), str(p.get("text") or "")[:MAX_PAGE_CHARS]) for p in pages[:MAX_PAGES]]
        if not any(t.strip() for _, t in texts):
            raise PolicyKBError("UPLOAD_REJECTED", "the document has no readable text (a scan without OCR?); "
                                                   "ask the user for a text PDF")
        full = "\n".join(t for _, t in texts)
        in_scope = "arogya sanjeevani" in full.lower()
        detected = UIN_IN_TEXT.findall(full)
        detected_uin = detected[0] if detected else None
        warnings: list[str] = []
        if not in_scope:
            warnings.append("This does not look like an Arogya Sanjeevani policy: ClaimClear's checks may not apply.")
        if len(pages) > MAX_PAGES:
            warnings.append(f"only the first {MAX_PAGES} pages were indexed")
        info = WordingInfo(insurer="Uploaded by the policyholder",
                           product="Arogya Sanjeevani Policy" if in_scope else "Unknown product",
                           uin=f"upload:{document_id}", version=detected_uin or "")
        result = ingest_lines([t.splitlines() for _, t in texts], info)
        warnings += result.warnings
        clauses = [c for c in result.clauses if c.text]
        structure = "clauses"
        if len(clauses) < MIN_CLAUSES:
            structure = "pages"
            result.clauses = [Clause(f"Page {n}", f"Page {n}", t.strip(), "", None, n, n)
                              for n, t in texts if t.strip()]
            warnings.append(f"only {len(clauses)} numbered clauses were recognised; indexed page by page "
                            "(citations name the page)")
        kb = PolicyKB.build(result, embedder=embedder or os.environ.get(UPLOAD_EMBEDDER_ENV, "hashing"))
        path = self.uploads_root / case_id / f"{document_id}.json"
        kb.save(path)
        catalogue_match = detected_uin if detected_uin in self.entries else None
        if catalogue_match:
            warnings.append(f"This wording's UIN {catalogue_match} is in the catalogue: the reviewed copy can be used "
                            "instead.")
        return {"wording_uin": info.uin, "case_id": case_id, "document_id": document_id,
                "clause_count": len([c for c in kb.clauses if c.text]), "structure": structure,
                "in_scope": in_scope, "detected_uin": detected_uin, "catalogue_match": catalogue_match,
                "reviewed": False, "warnings": warnings}
