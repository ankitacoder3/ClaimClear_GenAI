"""The standard tool error and every error code a ClaimClear server or library can return.

Every server returns an error the caller can act on as a tool error whose text is JSON::

    {"code": "DOCUMENT_NOT_IN_CASE", "message": "...", "retryable": false}

``retryable`` is true only when the same call may succeed later (an upstream outage).
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str
    retryable: bool = False


def parse_tool_error(text: str) -> Optional[ToolErrorPayload]:
    """The payload inside a tool error's text (the SDK prefixes it with 'Error executing tool ...: ')."""
    if not text or "{" not in text:
        return None
    try:
        return ToolErrorPayload.model_validate(json.loads(text[text.index("{"): text.rindex("}") + 1]))
    except (ValueError, TypeError):
        return None


# server -> code -> what it means and what the caller does next
ERROR_CODES: dict[str, dict[str, str]] = {
    "settlement-engine": {
        "POLICY_MISMATCH": "claim.policy_no and policy.policy_no differ: load the case's own policy (get_policy)",
        "HISTORY_POLICY_MISMATCH": "the history holds claims on another policy: pass get_claim_history unchanged",
        "ROW_NOT_FOUND": "no such row on the letter: the message lists the valid row IDs",
        "UNKNOWN_HYPOTHESIS": "a hypothesis ID that doesn't exist: call list_hypotheses",
    },
    "case-records": {
        "CASE_NOT_FOUND": "no such case: the app gave a wrong case_id",
        "DOCUMENT_NOT_IN_CASE": "the document belongs to another case (or doesn't exist)",
        "DOCUMENT_INTEGRITY": "the stored copy is missing or changed: ask the user to upload it again",
        "POLICY_NOT_FOUND": "no pre-stored schedule for the policy: extract it from the uploaded policy and confirm",
        "INVALID_SCOPE": "claim-history scope not recognised",
        "INVALID_ROLE": "upload path: a document role that doesn't exist",
        "INVALID_POLICY": "upload path: setting a case's policy number to an empty value (set_policy)",
        "INVALID_WORDING": "upload path: a wording UIN in the wrong format",
        "UNSUPPORTED_MEDIA_TYPE": "upload path: only PDF, JPG and PNG are accepted",
        "FILE_TOO_LARGE": "upload path: the file is over 25 MB",
    },
    "document-reader": {
        "INVALID_CONTENT": "content_base64 is not valid base64",
        "UNSUPPORTED_MEDIA_TYPE": "only PDF, JPG and PNG are read",
        "MEDIA_TYPE_MISMATCH": "the bytes are not the declared type (a renamed file)",
        "DOCUMENT_TOO_LARGE": "the file is over 25 MB",
        "DOCUMENT_UNREADABLE": "empty, missing or can't be opened: ask for another copy",
        "DOCUMENT_ENCRYPTED": "the PDF is password-protected: ask for an unprotected copy",
        "PAGE_OUT_OF_RANGE": "a requested page doesn't exist",
    },
    "policy-kb": {
        "EMPTY_QUERY": "the search query is empty after cleaning",
        "INDEX_UNAVAILABLE": "the wording's index isn't built: run python -m policy_kb build",
        "NO_RULE_MAP": "the wording has no rule map (uploaded wordings): use search_clauses",
        "UNKNOWN_RULE": "a rule_ref the rule map doesn't have",
        "UNKNOWN_WORDING": "a wording UIN that isn't in the catalogue or the case",
        "UPLOAD_REJECTED": "the uploaded policy could not be indexed (out of scope or unreadable)",
        "UPSTREAM_UNAVAILABLE": "the embedding or rewriting service is down: retryable",
    },
    "insurer-portal": {
        "APPROVAL_REQUIRED": "no valid approval token for this exact letter: go back to the approval gate",
        "TEXT_HASH_MISMATCH": "the letter changed after approval: get a fresh approval",
        "GRIEVANCE_NOT_FOUND": "no grievance with that reference",
    },
    "memory": {
        "NO_CONSENT": "the user has not agreed to the memory policy: nothing is stored",
        "POLICY_VERSION": "consent was given to an older memory policy: ask again",
        "INVALID_USER": "user_id is not the app's opaque ID",
        "NOT_FINAL": "the audit still needs the user's answers: only final audits are stored",
        "MISSING_FIELD": "the case or audit lacks a field memory needs",
        "CLAIM_MISMATCH": "the audit belongs to another claim",
        "CLAIM_NOT_FOUND": "no remembered claim with that ID",
        "NOTHING_TO_DISPUTE": "the audit found nothing disputable: no grievance",
        "ROW_NOT_DISPUTABLE": "a grievance on a row the audit did not find disputable",
        "BAD_TRANSITION": "a grievance status change the lifecycle doesn't allow",
        "GRIEVANCE_NOT_FOUND": "no grievance with that ID for this user",
        "INVALID_HASH": "the approved text's hash is not a SHA-256",
        "SCHEMA_VERSION": "the memory database is from a newer version",
    },
}

RETRYABLE = frozenset({"UPSTREAM_UNAVAILABLE"})


def meaning(code: str, server: Optional[str] = None) -> str:
    """What a code means (searching every server when ``server`` is None); empty if unknown."""
    for name, codes in ERROR_CODES.items():
        if (server is None or name == server) and code in codes:
            return codes[code]
    return ""
