"""Record a live run's tool results once, replay them offline (tests and demos without the servers).

* ``RecordingToolkit(tk)`` wraps an open ``ClaimClearToolkit`` and records every typed call
  (method, arguments, result or error).
* ``ReplayToolkit(recording)`` answers the same calls from the recording, so the graph runs offline
  on **real engine outputs** (nothing here computes a figure). ``overrides`` replace a method to test
  a path the recording doesn't cover (an unreadable page, a missing policy, a disagreeing audit).
* ``file_grievance`` / ``grievance_status`` are simulated with the insurer-portal server's own checks
  (SHA-256 of the exact text; HMAC token when a gate secret is set), so the gate can be tested offline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable, Optional

from claimclear_tools.agents import TOOL_SERVER
from claimclear_tools.results import ERROR_ACTIONS, STOP, ClaimClearToolError, ToolErrorInfo

TYPED = sorted(set(TOOL_SERVER) | {"read_case", "ingest_uploaded_policy"})
PORTAL = ("file_grievance", "grievance_status")


def call_key(method: str, args: tuple, kwargs: dict) -> str:
    return json.dumps([method, list(args), kwargs], sort_keys=True, ensure_ascii=False, default=str)


def tool_error(tool: str, code: str, message: str = "") -> ClaimClearToolError:
    return ClaimClearToolError(ToolErrorInfo(tool, code, message or code, False, ERROR_ACTIONS.get(code, STOP)))


class RecordingToolkit:
    """Proxy that records every typed tool call of the wrapped toolkit."""

    def __init__(self, toolkit: Any):
        self._tk = toolkit
        self.calls: list[dict] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._tk, name)
        if name not in TYPED:
            return attr

        async def recorded(*args, **kwargs):
            entry = {"key": call_key(name, args, kwargs)}
            try:
                entry["result"] = await attr(*args, **kwargs)
            except ClaimClearToolError as exc:
                entry["error"] = {"tool": exc.info.tool, "code": exc.info.code, "message": exc.info.message}
                self.calls.append(entry)
                raise
            self.calls.append(entry)
            return entry["result"]

        return recorded


class ReplayToolkit:
    """Offline stand-in for ``ClaimClearToolkit``: recorded reads, a simulated insurer portal."""

    def __init__(self, calls: list[dict], overrides: Optional[dict[str, Callable]] = None,
                 gate_secret: Optional[str] = None):
        self._calls = {c["key"]: c for c in calls}
        self.overrides = dict(overrides or {})
        self.gate_secret = gate_secret
        self.filed: dict[str, dict] = {}
        self.log: list[str] = []

    async def __aenter__(self) -> "ReplayToolkit":     # usable where the real toolkit's ``async with`` is expected
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name not in TYPED:
            raise AttributeError(name)

        async def replay(*args, **kwargs):
            self.log.append(name)
            if name in self.overrides:
                return await _maybe_await(self.overrides[name](*args, **kwargs))
            if name in PORTAL:
                return getattr(self, f"_{name}")(*args, **kwargs)
            hit = self._calls.get(call_key(name, args, kwargs))
            if hit is None:
                raise KeyError(f"no recorded result for {name}{args}{kwargs}: re-record the fixture")
            if "error" in hit:
                e = hit["error"]
                raise tool_error(e["tool"], e["code"], e["message"])
            return json.loads(json.dumps(hit["result"]))     # a fresh copy each time

        return replay

    # ---- the insurer-portal server's checks (servers/insurer_portal/insurer_portal/app.py) ----
    def _file_grievance(self, case_id, claim_id, row_ids, text, text_sha256, approval_token):
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != text_sha256:
            raise tool_error("file_grievance", "TEXT_HASH_MISMATCH", "the text is not the one that was approved")
        if self.gate_secret:
            want = hmac.new(self.gate_secret.encode(), text_sha256.encode(), "sha256").hexdigest()
            if not hmac.compare_digest(approval_token, want):
                raise tool_error("file_grievance", "APPROVAL_REQUIRED", "the approval token was not issued for this text")
        ref = "DRYRUN-" + hashlib.sha256(f"{case_id}|{text_sha256}".encode()).hexdigest()[:12].upper()
        dup = ref in self.filed
        self.filed.setdefault(ref, {"case_id": case_id, "claim_id": claim_id, "row_ids": row_ids, "text": text})
        return {"reference": ref, "status": "dry_run", "filed_at": "2026-01-01T00:00:00+00:00",
                "text_sha256": text_sha256, "duplicate": dup, "dry_run": True}

    def _grievance_status(self, reference):
        g = self.filed.get(reference)
        if g is None:
            raise tool_error("grievance_status", "GRIEVANCE_NOT_FOUND")
        return {"reference": reference, "case_id": g["case_id"], "claim_id": g["claim_id"], "status": "dry_run",
                "last_update": "2026-01-01T00:00:00+00:00", "insurer_response": None, "dry_run": True}


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
