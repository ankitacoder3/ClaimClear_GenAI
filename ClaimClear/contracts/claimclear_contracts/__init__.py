"""ClaimClear contracts: what Member 2's tools and Member 3's agents both import.

    from claimclear_contracts import CaseState, Plan, ReaderHandoff, GrievanceDraft, tools, wording_for

* ``state``     CaseState (the LangGraph state) and which schema each field follows
* ``handoffs``  typed messages between agents, and the plan object shown to the user
* ``tools``     every MCP tool's input/output schema (exported from the servers' snapshots)
* ``errors``    the standard tool error and every error code
* ``verdicts``  verdict labels and the only wording an explanation may use
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from . import errors, handoffs, state, tools, verdicts
from .errors import ERROR_CODES, ToolErrorPayload, parse_tool_error
from .handoffs import (
    AgentName,
    AnalystHandoff,
    AuditorHandoff,
    CriticFailure,
    CriticReport,
    ExplainerDraft,
    ExplanationSentence,
    GrievanceDraft,
    Plan,
    PlanStep,
    ReaderHandoff,
    UnreadablePage,
)
from .state import FIELD_SHAPES, CaseState, engine_case
from .verdicts import VERDICT_WORDING, VERDICTS, may_offer_grievance, wording_for

__version__ = "0.1.0"

__all__ = ["AgentName", "AnalystHandoff", "AuditorHandoff", "CaseState", "CriticFailure", "CriticReport",
           "ERROR_CODES", "ExplainerDraft", "ExplanationSentence", "FIELD_SHAPES", "GrievanceDraft", "Plan",
           "PlanStep", "ReaderHandoff", "ToolErrorPayload", "UnreadablePage", "VERDICTS", "VERDICT_WORDING",
           "contract_schemas", "engine_case", "errors", "handoffs", "may_offer_grievance", "parse_tool_error",
           "state", "tools", "verdicts", "wording_for"]


def contract_schemas() -> dict[str, Any]:
    """JSON schemas of everything defined here (pinned by ``snapshots/contracts.json``)."""
    out = {m.__name__: m.model_json_schema() for m in handoffs.HANDOFFS}
    out["CaseState"] = TypeAdapter(CaseState).json_schema()
    out["ToolErrorPayload"] = ToolErrorPayload.model_json_schema()
    out["ERROR_CODES"] = ERROR_CODES
    out["VERDICT_WORDING"] = VERDICT_WORDING
    out["FIELD_SHAPES"] = {k: v._asdict() for k, v in FIELD_SHAPES.items()}
    return out
