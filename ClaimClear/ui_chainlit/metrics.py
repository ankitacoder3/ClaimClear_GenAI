"""Prometheus metrics for the chat, counted from the events app.log() already writes (no change to the review code).

Served on CLAIMCLEAR_METRICS_PORT (inside the Docker image: 9100, read by Prometheus; nothing is served when it is
unset). Counts only: no names, amounts or document text ever become a label.

    claimclear_events_total{event}                 every logged event (uploads, questions, answers, ...)
    claimclear_reviews_total{outcome}              finished reviews by outcome (grievance_declined, tool_error, ...)
    claimclear_review_seconds                      review time, from review_start to its outcome (histogram)
    claimclear_deductions_total{verdict}           audited deduction rows by verdict
    claimclear_security_flags_total{source}        security findings (documents, chat, consistency)
    claimclear_errors_total{kind}                  handler errors, tool errors, guard errors
"""
from __future__ import annotations

import os
import time

try:
    from prometheus_client import Counter, Histogram, start_http_server
except ImportError:                                   # metrics are optional: the chat runs without them
    Counter = Histogram = start_http_server = None

_started = False
_review_started: dict[str, float] = {}

if Counter is not None:
    EVENTS = Counter("claimclear_events_total", "Logged chat events", ["event"])
    REVIEWS = Counter("claimclear_reviews_total", "Finished reviews by outcome", ["outcome"])
    REVIEW_SECONDS = Histogram("claimclear_review_seconds", "Review time in seconds",
                               buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 300))
    DEDUCTIONS = Counter("claimclear_deductions_total", "Audited deduction rows by verdict", ["verdict"])
    SECURITY = Counter("claimclear_security_flags_total", "Security findings", ["source"])
    ERRORS = Counter("claimclear_errors_total", "Errors", ["kind"])


def start() -> None:
    """Serve /metrics once, when CLAIMCLEAR_METRICS_PORT is set."""
    global _started
    port = os.environ.get("CLAIMCLEAR_METRICS_PORT")
    if _started or not port or start_http_server is None:
        return
    start_http_server(int(port), addr="127.0.0.1")
    _started = True


def observe(event: str, details: dict) -> None:
    """Update the counters from one app.log() event. Never raises: metrics must not break the chat."""
    if Counter is None:
        return
    try:
        EVENTS.labels(event=event).inc()
        case = str(details.get("case_id") or "")
        if event in ("review_start", "sample"):
            _review_started[case] = time.monotonic()
        elif event == "review_outcome":
            outcome = str(details.get("outcome") or "unknown")
            REVIEWS.labels(outcome=outcome).inc()
            if outcome in ("tool_error", "error"):
                ERRORS.labels(kind="review").inc()
            started = _review_started.pop(case, None) or (_review_started.popitem()[1] if _review_started else None)
            if started:
                REVIEW_SECONDS.observe(time.monotonic() - started)
        elif event == "findings":
            for verdict in (details.get("rows") or {}).values():
                DEDUCTIONS.labels(verdict=str(verdict)).inc()
        elif event == "security_files":
            n = sum(len(f.get("findings") or []) for f in details.get("files") or [])
            if n:
                SECURITY.labels(source="documents").inc(n)
        elif event == "security_chat":
            SECURITY.labels(source="chat").inc(len(details.get("findings") or []) or 1)
        elif event == "consistency":
            n = len(details.get("findings") or [])
            if n:
                SECURITY.labels(source="consistency").inc(n)
        elif event == "security_guard_errors":
            ERRORS.labels(kind="guard").inc()
        elif event == "handler_error":
            ERRORS.labels(kind="handler").inc()
    except Exception:                                 # noqa: BLE001
        pass
