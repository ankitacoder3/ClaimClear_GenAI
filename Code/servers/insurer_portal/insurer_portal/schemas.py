"""Typed inputs and outputs of the insurer-portal MCP tools (the interface).

Member 2 defines this interface; Member 4 builds the mock insurer portal behind it. Until then
the server runs a **dry-run backend**: it checks every filing exactly as the real one must, keeps a
record, and files nothing. Pinned by ``tests/snapshots/insurer_portal_tools.json``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CASE_ID = Field(pattern=r"^case_[0-9a-f]{16}$", description="The case the grievance is about")
REFERENCE = Field(pattern=r"^[A-Z]{2,8}-[0-9A-F]{8,16}$", max_length=30,
                  description="The portal's reference from file_grievance")

Status = Literal["dry_run", "filed", "acknowledged", "resolved", "rejected", "escalated", "closed"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileGrievanceOut(_Out):
    reference: str = Field(description="Keep it: grievance_status and claimclear_memory update_grievance use it")
    status: Status = Field(description="dry_run while the mock portal isn't connected; nothing was sent")
    filed_at: str = Field(description="ISO time the portal accepted it")
    text_sha256: str = Field(description="SHA-256 of the exact text that was filed")
    duplicate: bool = Field(description="True when this exact text was already filed for the case; the earlier "
                                        "reference is returned and nothing is filed twice")
    dry_run: bool


class GrievanceStatusOut(_Out):
    reference: str
    case_id: str
    claim_id: str
    status: Status
    last_update: str
    insurer_response: Optional[str]
    dry_run: bool
