"""Reading tool results and errors.

``langchain-mcp-adapters`` tools return a ``ToolMessage`` when invoked as a tool
call (as LangGraph's ``ToolNode`` does):

* the typed result is in ``message.artifact["structured_content"]``;
* errors don't raise: the content is the text
  ``Error executing tool <name>: {"code": ..., "message": ..., "retryable": ...}``,
  or a schema-validation message when the arguments were malformed.

These helpers work on any object with ``content`` and ``artifact`` attributes, so
they need no LangChain import and are easy to test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

ERROR_PREFIX = "Error executing tool"

# What the graph should do for each error code.
STOP = "stop"                                  # programming or isolation error: don't retry
ASK_FOR_DOCUMENT = "ask_user_for_document"     # missing-document edge
FIX_PAGES = "fix_pages_and_retry"
ASK_POLICY_NUMBER = "ask_user_to_confirm_policy"
FIX_CASE = "fix_case_assembly"
RETRY_VALID_ROW = "retry_with_a_valid_row"
PICK_HYPOTHESES = "call_list_hypotheses_and_pick_again"
SEND_BACK_TO_READER = "send_back_to_document_reader"
CONTINUE_WITHOUT_CITATIONS = "continue_without_citations"   # explain from engine rule summaries, marked as summaries
RETRY_LATER = "retry_later"                                 # retryable outage (rate limit, provider down)
USE_SEARCH_CLAUSES = "use_search_clauses"                   # no reviewed rule map: search the wording instead
REPHRASE_QUERY = "rephrase_query"
BACK_TO_APPROVAL = "return_to_approval_gate"                 # the filed text must be the approved text

ERROR_ACTIONS: dict[str, str] = {
    "CASE_NOT_FOUND": STOP,
    "DOCUMENT_NOT_IN_CASE": STOP,
    "DOCUMENT_INTEGRITY": STOP,
    "DOCUMENT_UNREADABLE": ASK_FOR_DOCUMENT,
    "DOCUMENT_ENCRYPTED": ASK_FOR_DOCUMENT,
    "PAGE_OUT_OF_RANGE": FIX_PAGES,
    "POLICY_NOT_FOUND": ASK_POLICY_NUMBER,
    "INVALID_SCOPE": STOP,
    "POLICY_MISMATCH": FIX_CASE,
    "HISTORY_POLICY_MISMATCH": FIX_CASE,
    "ROW_NOT_FOUND": RETRY_VALID_ROW,
    "UNKNOWN_HYPOTHESIS": PICK_HYPOTHESES,
    "INVALID_ARGUMENTS": SEND_BACK_TO_READER,
    # policy-kb
    "INDEX_UNAVAILABLE": CONTINUE_WITHOUT_CITATIONS,
    "UPSTREAM_UNAVAILABLE": RETRY_LATER,
    "NO_RULE_MAP": USE_SEARCH_CLAUSES,
    "UNKNOWN_RULE": USE_SEARCH_CLAUSES,
    "EMPTY_QUERY": REPHRASE_QUERY,
    "UNKNOWN_WORDING": STOP,
    "UPLOAD_REJECTED": ASK_FOR_DOCUMENT,
    # insurer-portal
    "TEXT_HASH_MISMATCH": BACK_TO_APPROVAL,
    "APPROVAL_REQUIRED": BACK_TO_APPROVAL,
    "GRIEVANCE_NOT_FOUND": STOP,
}


@dataclass(frozen=True)
class ToolErrorInfo:
    """A tool error, with what the graph should do about it."""

    tool: str
    code: str
    message: str
    retryable: bool
    action: str


class ClaimClearToolError(Exception):
    """Raised by ``ClaimClearToolkit.call`` and the typed helpers when a tool returns an error."""

    def __init__(self, info: ToolErrorInfo):
        super().__init__(f"{info.tool}: {info.code}: {info.message}")
        self.info = info


def message_text(msg: Any) -> str:
    """The text content of a ToolMessage (string or list of content blocks)."""
    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def structured(msg: Any) -> Optional[dict]:
    """The typed result, or ``None`` if there is none.

    MCP tools put it in ``artifact["structured_content"]``. In-process tools (such as
    ``policy_kb.tools.make_tools``) have no artifact; their content is the result as JSON.
    """
    artifact = getattr(msg, "artifact", None)
    if isinstance(artifact, dict):
        value = artifact.get("structured_content")
        return value if isinstance(value, dict) else None
    text = message_text(msg).strip()
    if artifact is None and text.startswith("{"):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
    return None


def tool_error(msg: Any) -> Optional[ToolErrorInfo]:
    """The error a tool returned, or ``None`` if the call succeeded."""
    text = message_text(msg).strip()
    if not text.startswith(ERROR_PREFIX):
        return None
    head, _, rest = text.partition(":")
    tool = head[len(ERROR_PREFIX):].strip()
    rest = rest.strip()
    if rest.startswith("{"):
        try:
            data = json.loads(rest)
            code = str(data.get("code", "UNKNOWN"))
            return ToolErrorInfo(tool, code, str(data.get("message", "")), bool(data.get("retryable", False)),
                                 ERROR_ACTIONS.get(code, STOP))
        except json.JSONDecodeError:
            pass
    return ToolErrorInfo(tool, "INVALID_ARGUMENTS", rest, False, SEND_BACK_TO_READER)
