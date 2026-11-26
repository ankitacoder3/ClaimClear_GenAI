"""The chat's Prometheus counters, updated from its log events (ui_chainlit/metrics.py). No server is started."""
from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")
import metrics  # noqa: E402


def value(name, **labels):
    return prometheus_client.REGISTRY.get_sample_value(name, labels) or 0


def test_events_become_counts_without_any_personal_data():
    before = (value("claimclear_reviews_total", outcome="grievance_declined"),
              value("claimclear_deductions_total", verdict="does_not_match_policy"),
              value("claimclear_security_flags_total", source="documents"), value("claimclear_errors_total", kind="guard"))
    metrics.observe("review_start", {"case_id": "case_1"})
    metrics.observe("findings", {"rows": {"R1": "matches_policy", "R4": "does_not_match_policy"}})
    metrics.observe("security_files", {"files": [{"name": "letter.pdf", "findings": ["injection"]}]})
    metrics.observe("security_guard_errors", {"errors": {}})
    metrics.observe("review_outcome", {"outcome": "grievance_declined"})
    after = (value("claimclear_reviews_total", outcome="grievance_declined"),
             value("claimclear_deductions_total", verdict="does_not_match_policy"),
             value("claimclear_security_flags_total", source="documents"), value("claimclear_errors_total", kind="guard"))
    assert [a - b for a, b in zip(after, before)] == [1, 1, 1, 1]
    assert value("claimclear_review_seconds_count") >= 1


def test_a_bad_event_never_breaks_the_chat():
    metrics.observe("findings", {"rows": "not a dict"})          # swallowed
    metrics.observe("security_files", {"files": [None]})
