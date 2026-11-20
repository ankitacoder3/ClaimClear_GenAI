"""Case and document store.

Uploaded documents are copied in under **neutral IDs** (``doc_`` + 16 hex digits
of their SHA-256) and neutral file names, so nothing that reaches a model can
leak a label through a file name or folder (the dataset's names such as
``MAL-01.pdf`` or ``4_adversarial/`` would). A case groups the documents of one
claim and records the policy number it belongs to; tools only ever read within
one case.

Per case, the upload path may also record what the app learned about each document: the user's own file name
(only when the caller passes one: the chat does, dataset registration never does, so dataset labels still can't
leak), and a one-line summary with the document's role (``describe_document``). The page count is read once when
the file is added.

Layout under the store root (development)::

    index.json                 cases and documents (no dataset file names)
    files/<document_id>.<ext>  the stored copies

In production the index lives in PostgreSQL and the files in MinIO, with the same
records and names (``backends.py``: ``CLAIMCLEAR_CASE_INDEX``, ``CLAIMCLEAR_BLOB_STORE``).

The store is written only by the upload path (the app, or ``register_dataset``
for development). The MCP tools only read it.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .backends import Blobs, Index, blobs_for, index_for

STORE_ENV = "CLAIMCLEAR_CASE_STORE"
DEFAULT_WORDING_ENV = "CLAIMCLEAR_DEFAULT_WORDING_UIN"
DEFAULT_WORDING_UIN = "GODHLIP24179V022324"   # the reviewed catalogue wording the pre-stored schedules use
# What a document is, within its case. "policy_wording" and "policy_schedule" are for a policy the user
# uploads because theirs is not in the catalogue.
ROLES = ("bill", "settlement_letter", "discharge_summary", "policy_wording", "policy_schedule", "other")
WORDING_UIN = re.compile(r"^([A-Z]{7}\d{5}V\d{6}|upload:doc_[0-9a-f]{16})$")
MEDIA_TYPES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MAX_BYTES = 25 * 1024 * 1024
ID_PATTERN = re.compile(r"^(doc|case)_[0-9a-f]{16}$")


class StoreError(Exception):
    """Something the caller can fix (unknown ID, wrong case, bad file)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    media_type: str
    sha256: str
    size_bytes: int
    stored_name: str  # neutral, e.g. doc_3fa2....pdf
    page_count: Optional[int] = None  # read when added; None for records stored before it was kept


@dataclass
class CaseRecord:
    case_id: str
    policy_no: str
    document_ids: list[str] = field(default_factory=list)
    wording_uin: str = ""                                          # "" = the default catalogue wording
    document_roles: dict[str, str] = field(default_factory=dict)  # document_id -> role in this case
    reference_key: str = ""         # picks this case's own reference record when a dataset reuses a policy number
    document_names: dict[str, str] = field(default_factory=dict)      # document_id -> the user's file name
    document_summaries: dict[str, str] = field(default_factory=dict)  # document_id -> one line on what it is

    def effective_wording_uin(self) -> str:
        return self.wording_uin or os.environ.get(DEFAULT_WORDING_ENV, DEFAULT_WORDING_UIN)

    def wording_source(self) -> str:
        return "uploaded" if self.effective_wording_uin().startswith("upload:") else "catalogue"


def default_store_dir() -> Path:
    env = os.environ.get(STORE_ENV)
    if env:
        return Path(env)
    # case_records/ -> case_records (project) -> servers -> repo root
    return Path(__file__).resolve().parents[3] / "var" / "case_store"


class CaseStore:
    """Cases and documents under neutral IDs, over a pluggable index and file store (see ``backends.py``)."""

    def __init__(self, root: Optional[str | Path] = None, index: Optional[Index] = None,
                 blobs: Optional[Blobs] = None):
        self.root = Path(root) if root else default_store_dir()
        self.index = index or index_for(self.root)
        self.blobs = blobs or blobs_for(self.root)
        documents, cases = self.index.load()
        self._docs: dict[str, DocumentRecord] = {d["document_id"]: DocumentRecord(**d) for d in documents}
        self._cases: dict[str, CaseRecord] = {c["case_id"]: CaseRecord(**c) for c in cases}

    # ------------------------------------------------------------------ writing (upload path only)

    def _save(self) -> None:
        self.index.save([asdict(d) for d in self._docs.values()], [asdict(c) for c in self._cases.values()])

    def create_case(self, policy_no: str, salt: str = "", wording_uin: str = "", reference_key: str = "") -> CaseRecord:
        """A new case for ``policy_no``. ``salt`` makes the ID reproducible (dataset registration).

        ``wording_uin`` is the policy wording the user selected from the catalogue (an IRDAI UIN); leave it
        empty for the default wording. For an uploaded policy, call ``set_wording`` after indexing it.
        ``reference_key`` is set only by dataset registration (see ``reference.py``); uploads leave it empty.
        """
        _check_wording(wording_uin)
        seed = salt or os.urandom(16).hex()
        case_id = "case_" + hashlib.sha256(f"{policy_no}|{seed}".encode()).hexdigest()[:16]
        if case_id not in self._cases:
            self._cases[case_id] = CaseRecord(case_id, policy_no, wording_uin=wording_uin, reference_key=reference_key)
            self._save()
        return self._cases[case_id]

    def set_wording(self, case_id: str, wording_uin: str) -> CaseRecord:
        """Point a case at a wording: a catalogue UIN, or ``upload:doc_...`` once the upload is indexed."""
        _check_wording(wording_uin)
        case = self.case(case_id)
        if wording_uin.startswith("upload:") and wording_uin.split(":", 1)[1] not in case.document_ids:
            raise StoreError("DOCUMENT_NOT_IN_CASE", f"{wording_uin} is not a document of case {case_id}")
        case.wording_uin = wording_uin
        self._save()
        return case

    def add_document(self, case_id: str, path: str | Path, role: str = "other", name: str = "") -> DocumentRecord:
        """Copy a PDF, JPG or PNG into the store and attach it to the case with its ``role``. ``name``: the user's
        own file name, kept for this case only (leave it empty for dataset files)."""
        if role not in ROLES:
            raise StoreError("INVALID_ROLE", f"role must be one of {', '.join(ROLES)}")
        path = Path(path)
        case = self.case(case_id)
        ext = path.suffix.lower()
        if ext not in MEDIA_TYPES:
            raise StoreError("UNSUPPORTED_MEDIA_TYPE", f"only PDF, JPG and PNG are accepted, not {ext or 'no extension'}")
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise StoreError("FILE_TOO_LARGE", f"{size} bytes is over the {MAX_BYTES} byte limit")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        document_id = "doc_" + digest[:16]
        if document_id not in self._docs:
            stored = f"{document_id}{'.jpg' if ext == '.jpeg' else ext}"
            self.blobs.put(stored, data, MEDIA_TYPES[ext])
            self._docs[document_id] = DocumentRecord(document_id, MEDIA_TYPES[ext], digest, size, stored,
                                                     _page_count(data, MEDIA_TYPES[ext]))
        if document_id not in case.document_ids:
            case.document_ids.append(document_id)
        case.document_roles[document_id] = role
        if name:
            case.document_names[document_id] = Path(name).name[:200]
        self._save()
        return self._docs[document_id]

    def describe_document(self, case_id: str, document_id: str, role: Optional[str] = None,
                          summary: Optional[str] = None) -> CaseRecord:
        """Record what a document of the case is: its ``role`` and/or a one-line ``summary`` (what the app or its
        agent read off the document). Only what is given changes."""
        case = self.case(case_id)
        if document_id not in case.document_ids:
            raise StoreError("DOCUMENT_NOT_IN_CASE", f"document {document_id!r} is not part of case {case_id!r}")
        if role is not None:
            if role not in ROLES:
                raise StoreError("INVALID_ROLE", f"role must be one of {', '.join(ROLES)}")
            case.document_roles[document_id] = role
        if summary is not None:
            case.document_summaries[document_id] = " ".join(summary.split())[:500]
        self._save()
        return case

    def set_policy(self, case_id: str, policy_no: str, reference_key: str = "") -> CaseRecord:
        """Set the case's policy number once it is known (e.g. read off an uploaded schedule after the case was
        created). ``reference_key``: as in ``create_case`` (dataset registration only)."""
        case = self.case(case_id)
        if not policy_no.strip():
            raise StoreError("INVALID_POLICY", "the policy number is empty")
        case.policy_no = policy_no.strip()
        case.reference_key = reference_key
        self._save()
        return case

    # ------------------------------------------------------------------ reading (tools)

    def case(self, case_id: str) -> CaseRecord:
        if not ID_PATTERN.match(case_id or "") or case_id not in self._cases:
            raise StoreError("CASE_NOT_FOUND", f"no case {case_id!r}")
        return self._cases[case_id]

    def read(self, case_id: str, document_id: str) -> tuple[DocumentRecord, bytes]:
        """The document and its bytes, only if it belongs to ``case_id`` and its hash still matches."""
        case = self.case(case_id)
        if document_id not in case.document_ids:
            raise StoreError("DOCUMENT_NOT_IN_CASE", f"document {document_id!r} is not part of case {case_id!r}")
        record = self._docs[document_id]
        data = self.blobs.get(record.stored_name)
        if data is None or hashlib.sha256(data).hexdigest() != record.sha256:
            raise StoreError("DOCUMENT_INTEGRITY", f"stored copy of {document_id} is missing or has changed")
        return record, data

    def document(self, case_id: str, document_id: str) -> tuple[DocumentRecord, Path]:
        """The document and its local path (development file store only; production code uses ``read``)."""
        record, _ = self.read(case_id, document_id)
        path = self.blobs.path(record.stored_name)
        if path is None:
            raise StoreError("DOCUMENT_INTEGRITY", "this file store has no local paths; use read()")
        return record, path

    def documents(self, case_id: str) -> list[DocumentRecord]:
        return [self._docs[d] for d in self.case(case_id).document_ids]

    def role(self, case_id: str, document_id: str) -> str:
        return self.case(case_id).document_roles.get(document_id, "other")


def _page_count(data: bytes, media_type: str) -> Optional[int]:
    """Pages of a PDF (an image is one page); None when the file can't be opened."""
    if media_type != "application/pdf":
        return 1
    try:
        import pymupdf
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            return pdf.page_count
    except Exception:                       # unreadable or encrypted: the reader reports it on the first read
        return None


def _check_wording(wording_uin: str) -> None:
    if wording_uin and not WORDING_UIN.match(wording_uin):
        raise StoreError("INVALID_WORDING", f"{wording_uin!r} is not an IRDAI UIN or upload:doc_<id>")
