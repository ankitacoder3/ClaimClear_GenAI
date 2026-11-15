"""The insurer-portal MCP server: the interface, with a dry-run backend.

    file_grievance     WRITE: file the approved grievance text. The only write tool in ClaimClear; only the
                       grievance agent holds it, and only after the approval gate (Member 4).
    grievance_status   read: the status of a filed grievance.

What ``file_grievance`` checks, in the dry run exactly as the real portal must:

* ``sha256(text) == text_sha256``: the text being filed is the text whose hash was approved
  (``TEXT_HASH_MISMATCH`` otherwise; an edit after approval is refused);
* an ``approval_token`` is present. When ``CLAIMCLEAR_GATE_SECRET`` is set, the token must equal
  ``HMAC-SHA256(secret, text_sha256)``, the token the approval gate issues (``APPROVAL_REQUIRED``
  otherwise). Member 4's gate and permission hook replace this check with their own;
* the same text for the same case is filed once (``duplicate: true`` returns the first reference).

The dry-run backend records filings in a JSON file (``$CLAIMCLEAR_PORTAL_STORE``, default
``var/insurer_portal/dry_run.json``) and sends nothing anywhere. Member 4 swaps ``DryRunPortal``
for a client of the mock portal's API; the tool names, inputs and outputs stay the same.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from .schemas import CASE_ID, REFERENCE, FileGrievanceOut, GrievanceStatusOut

log = logging.getLogger("claimclear.insurer_portal")

SERVER_NAME = "insurer-portal"
STORE_ENV = "CLAIMCLEAR_PORTAL_STORE"
SECRET_ENV = "CLAIMCLEAR_GATE_SECRET"

INSTRUCTIONS = """\
ClaimClear insurer portal (dry run until the mock portal is connected).

Rules for callers:
- Call file_grievance only after the policyholder approved the exact text at the approval gate;
  pass that text unchanged with its SHA-256 and the gate's approval_token.
- Never change the text after approval: the hash check refuses it.
- Keep the returned reference; use grievance_status to follow up.
- status "dry_run" means nothing was sent to an insurer: say so to the user.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


def _error(code: str, message: str, retryable: bool = False) -> ToolError:
    return ToolError(json.dumps({"code": code, "message": message, "retryable": retryable}))


def default_store_path() -> Path:
    env = os.environ.get(STORE_ENV)
    return Path(env) if env else Path(__file__).resolve().parents[3] / "var" / "insurer_portal" / "dry_run.json"


def expected_token(secret: str, text_sha256: str) -> str:
    """The approval token the gate issues for a text hash (HMAC-SHA256, hex)."""
    return hmac.new(secret.encode("utf-8"), text_sha256.encode("utf-8"), "sha256").hexdigest()


class Portal(Protocol):
    """What Member 4's mock-portal client must provide."""

    def file(self, case_id: str, claim_id: str, row_ids: list[str], text: str, text_sha256: str) -> dict: ...

    def status(self, reference: str) -> Optional[dict]: ...


class DryRunPortal:
    """Records filings in a JSON file; sends nothing."""

    def __init__(self, path: Path, clock=lambda: datetime.now(timezone.utc)):
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def file(self, case_id: str, claim_id: str, row_ids: list[str], text: str, text_sha256: str) -> dict:
        with self._lock:
            data = self._load()
            for ref, g in data.items():
                if g["case_id"] == case_id and g["text_sha256"] == text_sha256:
                    return {**self._out(ref, g), "duplicate": True}
            ref = "DRYRUN-" + hashlib.sha256(f"{case_id}|{text_sha256}".encode()).hexdigest()[:12].upper()
            now = self._clock().isoformat(timespec="seconds")
            data[ref] = {"case_id": case_id, "claim_id": claim_id, "row_ids": row_ids, "text_sha256": text_sha256,
                         "status": "dry_run", "filed_at": now, "last_update": now, "insurer_response": None}
            self._save(data)
            return {**self._out(ref, data[ref]), "duplicate": False}

    def status(self, reference: str) -> Optional[dict]:
        g = self._load().get(reference)
        if g is None:
            return None
        return {"reference": reference, "case_id": g["case_id"], "claim_id": g["claim_id"], "status": g["status"],
                "last_update": g["last_update"], "insurer_response": g["insurer_response"], "dry_run": True}

    @staticmethod
    def _out(ref: str, g: dict) -> dict:
        return {"reference": ref, "status": g["status"], "filed_at": g["filed_at"], "text_sha256": g["text_sha256"],
                "dry_run": True}


def create_server(portal: Optional[Portal] = None, gate_secret: Optional[str] = None) -> MCPServer:
    """Build the server. ``portal`` defaults to the dry-run backend; ``gate_secret`` (or
    ``$CLAIMCLEAR_GATE_SECRET``) turns on the approval-token check."""
    backend = portal or DryRunPortal(default_store_path())
    secret = gate_secret if gate_secret is not None else os.environ.get(SECRET_ENV, "")
    log.info("insurer portal: %s; approval-token check %s", type(backend).__name__, "on" if secret else "presence only")
    server = MCPServer(name=SERVER_NAME, title="ClaimClear insurer portal (dry run)", version="0.1.0",
                       instructions=INSTRUCTIONS)

    @server.tool(
        title="File grievance",
        description=(
            "WRITE. File the grievance text the policyholder approved at the approval gate. Pass the exact text, "
            "its SHA-256 and the gate's approval_token. Returns a reference to follow up with. In dry-run mode "
            "nothing is sent to the insurer (status 'dry_run')."),
        annotations=WRITE, meta={"access": "write", "requires": "approval_token"})
    def file_grievance(case_id: Annotated[str, CASE_ID],
                       claim_id: Annotated[str, Field(min_length=1, max_length=64)],
                       row_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=32)]],
                                          Field(min_length=1, max_length=50,
                                                description="The disputable letter rows the grievance covers")],
                       text: Annotated[str, Field(min_length=50, max_length=20000,
                                                  description="The exact approved grievance text")],
                       text_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
                       approval_token: Annotated[str, Field(min_length=16, max_length=256)]) -> FileGrievanceOut:
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != text_sha256:
            raise _error("TEXT_HASH_MISMATCH", "the text is not the one that was approved (its SHA-256 differs); "
                                               "send it back to the approval gate")
        if secret and not hmac.compare_digest(approval_token, expected_token(secret, text_sha256)):
            raise _error("APPROVAL_REQUIRED", "the approval token was not issued for this text")
        return FileGrievanceOut.model_validate(backend.file(case_id, claim_id, list(row_ids), text, text_sha256))

    @server.tool(
        title="Grievance status",
        description="The current status of a filed grievance, by the reference file_grievance returned.",
        annotations=READ_ONLY, meta={"access": "read"})
    def grievance_status(reference: Annotated[str, REFERENCE]) -> GrievanceStatusOut:
        found = backend.status(reference)
        if found is None:
            raise _error("GRIEVANCE_NOT_FOUND", f"no grievance with reference {reference!r}")
        return GrievanceStatusOut.model_validate(found)

    return server
