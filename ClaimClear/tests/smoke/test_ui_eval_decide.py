"""Gate C runs at most once per 4-hour window and only for an untested commit (tests/ui_eval_decide.py). No network."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui_eval_decide import decide  # noqa: E402

NOW = datetime(2026, 11, 26, 10, 30, tzinfo=timezone.utc)           # window 08:00-12:00 UTC
IN_WINDOW = {"created_at": "2026-11-26T08:40:00Z", "head_sha": "aaa1111"}
EARLIER = {"created_at": "2026-11-26T05:00:00Z", "head_sha": "aaa1111"}


def test_by_hand_always_runs():
    assert decide("workflow_dispatch", "bbb", [IN_WINDOW], 4, NOW)[0]


def test_a_push_runs_once_per_window():
    assert decide("push", "bbb2222", [EARLIER], 4, NOW)[0]                    # nothing yet in 08-12
    run, why = decide("push", "bbb2222", [IN_WINDOW], 4, NOW)
    assert not run and "08:00-12:00 UTC" in why                               # already ran in this window


def test_the_timer_runs_only_for_an_untested_commit():
    assert not decide("schedule", "aaa1111", [EARLIER], 4, NOW)[0]            # latest commit already tested
    assert decide("schedule", "bbb2222", [EARLIER], 4, NOW)[0]                # a push was skipped: test it now
    assert not decide("schedule", "bbb2222", [IN_WINDOW], 4, NOW)[0]          # but never twice in a window
    assert decide("push", "ccc3333", [], 4, NOW)[0]                           # first run ever
